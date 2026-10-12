-- =====================================================================
-- Cakezz + RuleLock AI : database schema (Supabase / Postgres)
-- Safe to re-run. Run the WHOLE file in the Supabase SQL Editor.
-- Order: tables -> indexes -> audit log + RPC -> RLS -> seed data.
-- NO card data is stored anywhere. NO CHECK on quantity/price/total:
-- the vulnerable shop (RuleLock OFF) must be able to store tampered values.
-- =====================================================================

-- ---------- 1. core shop tables ----------
create table if not exists users (
  id            bigint generated always as identity primary key,
  username      text not null unique,
  password_hash text not null,
  role          text not null default 'customer' check (role in ('customer','admin')),
  phone         text,
  created_at    timestamptz not null default now()
);

create table if not exists products (
  id          bigint generated always as identity primary key,
  name        text not null,
  description text not null default '',
  base_price  numeric not null default 0,
  stock       int not null default 0,
  image_path  text,
  active      boolean not null default true,
  sizes       jsonb
);

create table if not exists coupons (
  code    text primary key,
  percent int not null
);

create table if not exists orders (
  id               bigint generated always as identity primary key,
  order_number     text not null unique,            -- e.g. CZ-20261010123456
  user_id          bigint references users(id),
  status           text not null default 'PENDING'
                   check (status in ('PENDING','COMPLETED','PLACED','HELD','BLOCKED','CANCELLED','REFUSED')),
  payment_method   text not null check (payment_method in ('CARD','COD')),
  subtotal         numeric not null default 0,
  discount_value   numeric not null default 0,
  total            numeric not null default 0,
  coupons_applied  jsonb not null default '[]'::jsonb,
  cancelled_by     text,                            -- 'CUSTOMER' when the customer cancels
  rulelock_decision text,
  rulelock_reason   text,
  created_at       timestamptz not null default now()
);

create table if not exists order_items (
  id         bigint generated always as identity primary key,
  order_id   bigint not null references orders(id) on delete cascade,
  product_id bigint references products(id) on delete set null,
  quantity   bigint not null,                       -- no check: 0, negative, huge must be storable
  unit_price numeric not null
);

create table if not exists coupons_used (
  id       bigint generated always as identity primary key,
  user_id  bigint not null references users(id),
  code     text not null,
  order_id bigint references orders(id) on delete cascade
);

create table if not exists platform_settings (
  id               int primary key default 1 check (id = 1),   -- one single row
  rulelock_enabled boolean not null default false,
  updated_at       timestamptz not null default now()
);

-- ---------- 2. RuleLock tables ----------
create table if not exists transaction_events (
  event_id   uuid primary key default gen_random_uuid(),
  event_type text not null,                          -- LOGIN BROWSE ADD_TO_CART APPLY_COUPON CHECKOUT
  user_id    bigint,
  order_id   bigint,
  metadata   jsonb not null default '{}'::jsonb,     -- session_id, device_id, phone_hash, address_hash, ...
  created_at timestamptz not null default now()
);

create table if not exists account_restrictions (
  id         bigint generated always as identity primary key,
  user_id    bigint not null references users(id),
  type       text not null default 'rate_limit' check (type in ('rate_limit')),
  until      timestamptz not null,
  reason     text,
  created_at timestamptz not null default now()
);

-- ---------- 3. RuleLock audit log (immutable, insert-only) + RPC + one review per order ----------
-- This section is the team's own migrations, copied unchanged from data-collection/migrations/:
--   2026-10-03_rulelock_audit_log.sql        (table, indexes, insert-only trigger, RPC record_rulelock_review)
--   2026-10-03_rulelock_review_idempotency.sql (one review per order in transaction_events)
-- The third file (2026-10-03_backfill_order_reference.sql) is NOT run here: it only repairs old rows, a fresh
-- project has none, and the insert-only trigger below would reject that UPDATE if it ever matched a row.

-- Minimal immutable audit records for live and simulated RuleLock reviews.
-- Keep personal customer fields and raw request payloads out of this table.
CREATE TABLE IF NOT EXISTS public.rulelock_audit_log (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE,
    event_type text NOT NULL CHECK (event_type IN ('RULELOCK_REVIEW', 'RULELOCK_SIMULATION')),
    order_id bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    action text NOT NULL,
    decision text NOT NULL,
    reason text NOT NULL DEFAULT '',
    order_reference text,
    account_id text,
    payment_method text,
    total numeric,
    rule_code text,
    anomaly_score double precision
);

CREATE INDEX IF NOT EXISTS rulelock_audit_log_live_created_idx
    ON public.rulelock_audit_log (created_at DESC, audit_id DESC)
    WHERE event_type = 'RULELOCK_REVIEW';
CREATE INDEX IF NOT EXISTS rulelock_audit_log_live_decision_idx
    ON public.rulelock_audit_log (decision, created_at DESC)
    WHERE event_type = 'RULELOCK_REVIEW';
CREATE UNIQUE INDEX IF NOT EXISTS rulelock_audit_log_one_row_per_review
    ON public.rulelock_audit_log (event_type, order_id);

-- Backfill existing RuleLock events so the dashboard has a complete audit
-- history from the point this migration is applied. Keep only minimal fields.
INSERT INTO public.rulelock_audit_log (
    event_id, event_type, order_id, created_at, action, decision, reason,
    order_reference, account_id, payment_method, total, rule_code, anomaly_score
)
SELECT
    e.event_id,
    e.event_type,
    e.order_id,
    e.created_at,
    CASE e.metadata->>'decision'
        WHEN 'accept' THEN 'PASS'
        WHEN 'void_discount' THEN 'VOID'
        WHEN 'reject' THEN 'REJECT'
        WHEN 'hold' THEN 'HOLD'
        ELSE 'HOLD'
    END,
    COALESCE(e.metadata->>'decision', 'hold'),
    LEFT(COALESCE(e.metadata->>'reason', ''), 1000),
    LEFT(e.metadata->>'order_reference', 200),
    LEFT(e.metadata->>'account_id', 200),
    LEFT(e.metadata->>'payment_method', 40),
    CASE WHEN e.metadata->>'total' ~ '^-?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$'
         THEN (e.metadata->>'total')::numeric END,
    e.metadata->'rule_result'->>'rule_code',
    CASE WHEN e.metadata->'anomaly_result'->>'raw_score' ~ '^-?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$'
         THEN (e.metadata->'anomaly_result'->>'raw_score')::double precision END
FROM public.transaction_events AS e
WHERE e.event_type IN ('RULELOCK_REVIEW', 'RULELOCK_SIMULATION')
  AND e.event_id IS NOT NULL
  AND e.order_id IS NOT NULL
ON CONFLICT (event_id) DO NOTHING;

CREATE OR REPLACE FUNCTION public.reject_rulelock_audit_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'rulelock_audit_log is insert-only';
END;
$$;

DROP TRIGGER IF EXISTS rulelock_audit_log_immutable ON public.rulelock_audit_log;
CREATE TRIGGER rulelock_audit_log_immutable
    BEFORE UPDATE OR DELETE ON public.rulelock_audit_log
    FOR EACH ROW EXECUTE FUNCTION public.reject_rulelock_audit_mutation();

-- Use one PostgREST RPC transaction so every newly accepted transaction event
-- and its audit row commit together or both roll back.
CREATE OR REPLACE FUNCTION public.record_rulelock_review(p_event jsonb, p_audit jsonb)
RETURNS void LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
BEGIN
    INSERT INTO public.transaction_events (event_id, event_type, user_id, order_id, metadata)
    VALUES (
        (p_event->>'event_id')::uuid,
        p_event->>'event_type',
        NULLIF(p_event->>'user_id', '')::bigint,
        (p_event->>'order_id')::bigint,
        p_event->'metadata'
    );

    INSERT INTO public.rulelock_audit_log (
        event_id, event_type, order_id, created_at, action, decision, reason,
        order_reference, account_id, payment_method, total, rule_code, anomaly_score
    ) VALUES (
        (p_audit->>'event_id')::uuid,
        p_audit->>'event_type',
        (p_audit->>'order_id')::bigint,
        (p_audit->>'created_at')::timestamptz,
        p_audit->>'action',
        p_audit->>'decision',
        COALESCE(p_audit->>'reason', ''),
        p_audit->>'order_reference',
        p_audit->>'account_id',
        p_audit->>'payment_method',
        CASE WHEN p_audit->>'total' ~ '^-?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$'
             THEN (p_audit->>'total')::numeric END,
        p_audit->>'rule_code',
        CASE WHEN p_audit->>'anomaly_score' ~ '^-?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$'
             THEN (p_audit->>'anomaly_score')::double precision END
    );
END;
$$;

REVOKE ALL ON FUNCTION public.record_rulelock_review(jsonb, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.record_rulelock_review(jsonb, jsonb) TO service_role;

-- Enforce one RuleLock review record per numeric Cakely order.
-- Review code handles a duplicate insert by returning the existing result.
CREATE UNIQUE INDEX IF NOT EXISTS transaction_events_one_rulelock_review_per_order
    ON public.transaction_events (order_id)
    WHERE event_type = 'RULELOCK_REVIEW' AND order_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS transaction_events_one_rulelock_simulation_per_order
    ON public.transaction_events (order_id)
    WHERE event_type = 'RULELOCK_SIMULATION' AND order_id IS NOT NULL;

-- ---------- 4. helper indexes ----------
create index if not exists orders_user_created_idx   on orders (user_id, created_at desc);
create index if not exists order_items_order_idx     on order_items (order_id);
create index if not exists coupons_used_user_idx     on coupons_used (user_id);
create index if not exists events_created_idx        on transaction_events (created_at desc);
create index if not exists events_user_idx           on transaction_events (user_id);
create index if not exists restrictions_user_until_idx on account_restrictions (user_id, until desc);

-- ---------- 5. Row Level Security ----------
-- Only the servers (shop + RuleLock) talk to Supabase, with the secret / service-role
-- key, which bypasses RLS. RLS is ON with NO policies, so the public (anon) key
-- cannot read or write anything. The browser never talks to Supabase.
alter table users                enable row level security;
alter table products             enable row level security;
alter table coupons              enable row level security;
alter table orders               enable row level security;
alter table order_items          enable row level security;
alter table coupons_used         enable row level security;
alter table platform_settings    enable row level security;
alter table transaction_events   enable row level security;
alter table account_restrictions enable row level security;
alter table rulelock_audit_log   enable row level security;

-- ---------- 6. seed data ----------
insert into coupons (code, percent) values
  ('CAKE50', 50), ('CAKE20', 20), ('CAKE10', 10)
on conflict (code) do update set percent = excluded.percent;

insert into platform_settings (id, rulelock_enabled) values (1, false)
on conflict (id) do nothing;

-- Admin user: username 'admin', password 'admin123'.
-- The hash must come from PHP so that PHP's password_verify() accepts it.
-- Generate it with ONE of these (see docs/SETUP.md):
--   php -r 'echo password_hash("admin123", PASSWORD_DEFAULT), PHP_EOL;'
--   docker run --rm php:8.2-cli php -r 'echo password_hash("admin123", PASSWORD_DEFAULT), PHP_EOL;'
-- Then replace the text PASTE_PHP_HASH_HERE below (keep the single quotes) and run the file again.
-- While the placeholder is still there, the admin row is NOT changed.
insert into users (username, password_hash, role, phone)
values ('admin', '$2y$10$klsvT3MocTm2Q/qTBh0IEunGSWRfxXlodA2QjaQsj2Zb0kulY.M/2', 'admin', null)
on conflict (username) do update
  set password_hash = excluded.password_hash, role = 'admin'
  where excluded.password_hash <> '$2y$10$klsvT3MocTm2Q/qTBh0IEunGSWRfxXlodA2QjaQsj2Zb0kulY.M/2';
-- NOTE: on a brand-new database the first run inserts the admin row with the
-- placeholder (admin cannot log in yet). Paste the hash and re-run: it is then fixed.

-- No card data is seeded anywhere. No products are seeded (the admin adds them in the shop).
