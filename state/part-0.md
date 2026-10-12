Status: PARTIAL
Part: 0
Last session: 2026-10-11

## Done (short)
- `supabase/schema.sql` (all tables from BRIEF, RLS on with no policies, seeds, `record_rulelock_review` RPC, audit log with insert-only triggers, unique one-review-per-order indexes).
- `shop/.env.example`, `rulelock/.env.example`, `docker-compose.yml`, `docs/SETUP.md`, `supabase/README.md`.
- Folder README stubs already existed for shop and c1 to c4.

## Files created or changed
supabase/schema.sql, supabase/README.md (removed supabase/.gitkeep), shop/.env.example, rulelock/.env.example, docker-compose.yml, docs/SETUP.md

## Interfaces (exact function signatures / endpoints / tables touched)
Tables: users, products, coupons, orders, order_items, coupons_used, platform_settings (single row id=1), transaction_events, account_restrictions, rulelock_audit_log.
RPC (STAND-IN signature): `record_rulelock_review(p_order_id bigint, p_order_reference text, p_user_id bigint, p_decision text, p_reason text, p_rule_code text, p_payment_action text, p_anomaly_score numeric, p_account_action jsonb, p_pipeline jsonb) returns jsonb`. Idempotent on order_id.

## Env vars (name, meaning, default)
Shop: SUPABASE_URL, SUPABASE_SECRET_KEY, RULELOCK_URL, RULELOCK_API_TOKEN, RULELOCK_MOCK (0).
RuleLock: PORT 5001, SUPABASE_URL, SUPABASE_SECRET_KEY, RULELOCK_API_TOKEN, MAX_COUPONS 1, MAX_DISCOUNT_RATIO 0.6, MIN_QUANTITY 1, MAX_QUANTITY 20, PRICE_TOLERANCE 0.01, MIN_PURCHASE 500, TOTAL_TOLERANCE 1, COD_UNVERIFIED_HOLD_TOTAL 15000, COD_BAD_HOLD_COUNT 2, COD_BAD_REJECT_COUNT 3, COD_BAD_RATIO 0.5, COUPON_REVIEWS_24H_LIMIT 5, ANOMALY_HOLD_THRESHOLD -0.06, ANOMALY_REJECT_THRESHOLD -0.1, RATE_LIMIT_MINUTES 30.
(Variable names other than the ones in the part prompt are my choice; teammates' code was not attached. Parts 2 to 5 must use these names or update `rulelock/.env.example`.)

## How to run and test (and the test result you actually saw)
NOT TESTED. No Postgres or PHP in this sandbox and no network. Run `supabase/schema.sql` in a fresh Supabase project (steps in docs/SETUP.md).

## Kept / changed / why (reused teammate code)
Nothing reused: the three migration files were NOT attached.

## Decisions (anything you chose because the brief was unclear)
- Audit log table, indexes and RPC written from BRIEF/CONTRACT only (stand-in). No FK from the audit log to orders so the log survives order removal.
- No CHECK on quantity, prices or totals (the vulnerable path must store tampered values). `order_items.quantity` is bigint.
- `platform_settings` is a single row (`id = 1` check).
- Admin seed: first run inserts the placeholder hash; re-run after pasting the real hash fixes it (the update is skipped while the placeholder is present).
- No products seeded (admin adds them). `transaction_events` has no columns for session_id/device_id/phone_hash/address_hash: Part 5 should store them in `metadata`.

## Known issues
- UPDATE by Part 7: section 3 of `supabase/schema.sql` is now the team's real migrations (audit table, insert-only trigger, `record_rulelock_review(p_event, p_audit)`, one-review-per-order indexes), copied unchanged. The stand-in is gone. Still never run in a real Supabase project, so this part stays PARTIAL until `schema.sql` runs without errors.
- Not run against Supabase.
- Audit-log migration is a stand-in (see above).

## Requests to other parts
- Part 5 (c1): the shop sends `address_hash` and `phone_hash` as null when unknown (for example a visitor who is not logged in).

## Next step (only if PARTIAL: exact file and function to continue from)
1. Attach the three SQL files from `data-collection/migrations/` and replace section 3 of `supabase/schema.sql` (audit log + RPC + indexes) with them; keep table name `rulelock_audit_log`, RPC `record_rulelock_review`, the unique indexes. Re-check how c4/c1 call the RPC.
2. Run schema.sql in a fresh Supabase project. If it runs with no errors, change line 1 of this file to `Status: DONE`.
