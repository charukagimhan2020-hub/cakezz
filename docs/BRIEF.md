# PROJECT BRIEF (shared context for every part; lives in the repo as docs/BRIEF.md)

## Who and what
I am a university student building a demo for my project "RuleLock AI" (business-logic abuse detection for e-commerce), plus a deliberately vulnerable demo shop called "Cakezz" (a homemade cake shop). This is an educational lab that runs only on my own accounts. Every shop page shows a banner: "Intentionally vulnerable demo - do not use real data".

How to work with me:
- Explain in simple English. Keep explanations short.
- Give complete files with their paths, ready to paste into the repo.
- Do not add features that are not in this document. If something conflicts with CONTRACT.md, stop and ask me. For anything else that is unclear, choose the simplest option and write it under 'Decisions' in your state file.
- I have little time. Prefer the simplest thing that works.

## The demo
- Cakezz is built with plain PHP + HTML + CSS (no framework). LIGHT theme. It only needs to work, not look beautiful.
- Customers must sign up and log in to add to cart or buy. A product has: name, image, description, price, quantity box, "Add to cart" button, "Buy now" button.
- Coupons: only three, CAKE50 (50%), CAKE20 (20%), CAKE10 (10%). In the page, when one is selected the other two are greyed out and cannot be clicked. Coupons this account already used on earlier orders are greyed out too. This is front-end only (the backend does not enforce it).
- Payment: a fake card page (accepts anything, never validates, never stores the card data, always succeeds) or Cash on Delivery (COD).
- Admin login is admin / admin123. Admin can add, edit and delete products (name, image, description, price, stock), see and remove orders, and switch the "RuleLock AI" toggle. Admin does not review or approve orders.
- Toggle OFF: RuleLock is completely skipped and ALL these vulnerabilities work:
  1. The server trusts the unit price and total sent by the browser.
  2. Quantity can be 0, negative or huge.
  3. Coupons can be stacked or reused by editing the request.
  4. Unlimited COD orders, no account checks, no rate limit.
- Toggle ON: a new browser tab opens with the RuleLock monitor (DARK theme). Every checkout now goes through RuleLock. The tab shows the four steps, whether each passed, the reason when it failed, and the final result (accepted, discount voided, held, or blocked).
- There is no attack simulator. I attack by editing requests in browser dev tools or Burp Suite.

## Folder layout (the four RuleLock components stay as four separate folders)
```
cakezz/
  shop/                      PHP shop (light) + monitor page (dark) + assets/products/ images
  rulelock/
    c1-data-collection/      Charuka - Flask app: event ingestion, orchestration, Supabase access, audit APIs
    c2-rule-engine/          Sadini  - business rule validation
    c3-anomaly-detection/    Nihara  - Isolation Forest scoring
    c4-enforcement-engine/   Mishen  - decision logic + real actions + audit
  supabase/schema.sql
  docker-compose.yml  render.yaml  CONTRACT.md  README.md  STATE.md
  docs/      BRIEF.md (this file), SETUP.md, DEMO.md
  state/     part-N.md (one progress file per part, written by the session that did the part)
  scripts/   check_repo.py  pack.py  merge_parts.py  ownership.json  smoke_test.sh
```
Each component folder is its own Python package with its own tests and README (and a tiny optional Flask wrapper for standalone use). At runtime ONE Flask process runs (c1 imports c2, c3 and c4 as normal Python modules). Reason: Render free sleeps, and a chain of four sleeping services would time out.

## Hosting (free tiers only)
- Database: Supabase free. Both PHP and Flask talk to it through the Supabase REST API (PostgREST) with the secret key. No direct Postgres connection.
- Render free, two Docker services: "cakezz-shop" (php:8.2-apache) and "rulelock" (gunicorn).
- GitHub Pages cannot run PHP, so it is not used. The repo can still live on GitHub.
- Render free sleeps after about 15 minutes idle (30 to 60 s wake-up), so the shop uses a 60 s timeout when calling RuleLock, and treats a timeout or error as "hold".

## Database tables (Supabase, exact names)
- users(id bigint identity pk, username unique, password_hash, role 'customer'|'admin', phone, created_at)
- products(id bigint identity pk, name, description, base_price numeric, stock int, image_path, active bool default true, sizes jsonb null)
- orders(id bigint identity pk, order_number text unique e.g. 'CZ-20261010123456', user_id, status, payment_method 'CARD'|'COD', subtotal numeric, discount_value numeric, total numeric, coupons_applied jsonb, cancelled_by text null, rulelock_decision text null, rulelock_reason text null, created_at)
  - status values: PENDING, COMPLETED (card paid), PLACED (COD accepted), HELD, BLOCKED, CANCELLED, REFUSED
- order_items(id, order_id, product_id, quantity, unit_price)
- coupons(code pk, percent int)  rows: CAKE50 50, CAKE20 20, CAKE10 10
- coupons_used(id, user_id, code, order_id)
- platform_settings(id, rulelock_enabled bool default false, updated_at)
- transaction_events(event_id uuid pk, event_type, user_id bigint null, order_id bigint null, metadata jsonb, created_at default now())
- rulelock_audit_log: exactly as in the team's migration `2026-10-03_rulelock_audit_log.sql` (immutable, insert-only), plus the RPC `record_rulelock_review` and the one-review-per-order unique indexes.
- account_restrictions(id, user_id, type 'rate_limit', until timestamptz, reason, created_at)  (NEW)

## The contract
See `CONTRACT.md` in the repo root. It is the one source of truth. Do not copy it anywhere else.

## Themes
- Shop: LIGHT. White/cream background, dark text, one warm accent (for example #c2410c), readable system font, simple cards.
- RuleLock monitor: DARK. Near-black navy background (#0b1020), panels #121a30, monospace for numbers, status colors: PASS green #22c55e, VOID amber #f59e0b, HOLD orange #fb923c, REJECT red #ef4444. Style reference: the "Attack Simulation Lab" screenshot in my proposal (attached when needed). Define colors as CSS variables.

## Reusing my teammates' code
I will attach their code. Keep the code and logic that works. Upgrade or replace only what is unusable for this contract. Do not silently rewrite logic. Known problems in the current code that you should fix when your part touches them:
1. `data-collection/` holds copies of rules, decision, actions, features and model code that also exist in the other three folders. After this project each logic file lives in exactly ONE component folder.
2. `.env.example` uses `MAX_COUPONS_PER_SESSION`, but the code reads `MAX_COUPONS`. Use one name everywhere.
3. `rate_limit_account`, `hold_cod_order` and `void_discount` only return labels. They must really act (see c4 above).
4. No endpoint writes shopper events (`POST /events` is new).
5. The dashboard UI is not in the code; the monitor is built in the shop folder (Part 6).
6. The README mentions `docs/architecture.md` and `scripts/purge_old_events.py`, which are not in the zip. Do not depend on them.
7. The `model.joblib` file is created by `python train_model.py` at Docker build time. Keep that.

## Continuity
This is ONE app built over many sessions on different accounts. Sessions remember nothing; the repo zip and `state/part-N.md` are the only memory. The session rules are at the top of each PART prompt.
