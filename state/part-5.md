Status: DONE
Part: 5
Last session: 2026-10-11

## Done (short)
c1 cleaned and rebuilt as the orchestrator: `app.py`, `config.py`, `db.py`, `adapter.py`, `paths.py`, `pipeline.py`, `routes/events.py` (POST /events, POST /review-order, audit APIs incl. /audit-log/latest, toggle, summary, pipeline info), 49 tests, README; `rulelock/Dockerfile`, `rulelock/.env.example`, `rulelock/pyproject.toml`, `scripts/smoke_test.sh`.

## Files created or changed
rulelock/c1-data-collection/: app.py, config.py, db.py, adapter.py, paths.py, pipeline.py, routes/{__init__,events}.py, requirements.txt, README.md, tests/{c1_helpers,test_review_flow,test_events_and_auth,test_features_and_db}.py
rulelock/Dockerfile, rulelock/.env.example, rulelock/pyproject.toml, scripts/smoke_test.sh

## Interfaces (exact function signatures / endpoints / tables touched)
Endpoints (Bearer token, except /health and /ready): POST /events, POST /review-order, GET /audit-log, GET /audit-log/latest, GET /audit-log/<id_or_reference>, GET /dashboard/summary, GET+POST /settings/rulelock, GET /pipeline/info, GET /health, GET /ready.
`pipeline.run_review(body, store, order_id, order_reference, simulation=False, now=None) -> (response, info)`, `pipeline.compute_session_features(...)`, `pipeline.fallback_response(...)`, `adapter.StoreEnforcementDb(store)`.
Tables: reads products, coupons, users, orders, order_items, transaction_events, platform_settings; writes transaction_events (/events and via RPC), rulelock_audit_log (via RPC), orders and account_restrictions (via c4).
Supabase RPC used: `record_rulelock_review(p_event jsonb, p_audit jsonb)` (the TEAM's version, see Known issues).
Run: `gunicorn app:app` from `rulelock/c1-data-collection` (Docker: /app/c1-data-collection).

## Env vars (name, meaning, default)
c1: PORT 5001, APP_ENV (Docker: production = token required), SUPABASE_URL, SUPABASE_SECRET_KEY, RULELOCK_API_TOKEN, RULELOCK_ALLOW_NO_AUTH 0, CORS_ORIGINS (empty = off), MAX_BODY_BYTES 65536, EVENT_MAX_BYTES 8192, WEB_CONCURRENCY 1. c2/c3/c4 names are in `rulelock/.env.example` and match their own folders (MAX_QUANTITY_PER_LINE, MIN_PURCHASE_AMOUNT, COD_UNVERIFIED_ORDER_CAP, COD_BAD_HOLD, COD_BAD_REJECT, COD_BAD_RATIO, COUPON_VELOCITY_MAX_REVIEWS, PRICE_MATCH_TOLERANCE, TOTAL_TOLERANCE, MAX_COUPONS, MAX_DISCOUNT_RATIO, ANOMALY_HOLD_THRESHOLD, ANOMALY_REJECT_THRESHOLD, MODEL_PATH, RATE_LIMIT_MINUTES). `rulelock/.env.example` now uses the real names (this fixes the Part 0 draft).

## How to run and test (and the test result you actually saw)
`cd rulelock/c1-data-collection && pytest` (or `pytest` from `rulelock/`). pytest is not installed in this sandbox: the same 49 test functions ran with a plain-Python runner, 49 passed, 0 failed (uses the real c2, c3, c4; fake database; c3 model trained into a temp file; scikit-learn 1.8.0, not the pinned 1.5.1). `scripts/smoke_test.sh` ran over real HTTP against the Flask app backed by the fake database: clean order accept, coupon stacking void_discount, price tampering / quantity 9999 / tampered total reject, COD abuse reject, coupon burst reject (only /ready failed there, because that harness had no Supabase). NOT run: Docker build, gunicorn, real Supabase.

## Kept / changed / why (reused teammate code)
Kept: app/config/db structure, the review flow, idempotency per order (event type + order_id), Bearer auth with fail-closed, the audit RPC, audit/dashboard/toggle/info endpoints, simulation mode, session-feature counting. Changed or removed: see README ("Changes from the team's data-collection/ folder"). Teammate files not used: forwarder, static storefront, dashboard cookie login, old schema.sql/catalog.py, copies of the c2/c3/c4 code.

## Decisions (anything you chose because the brief was unclear)
- Any failed step: accept/void_discount become hold; a rule reject stays reject; storage failure keeps a reject, otherwise hold.
- Order context stored with a review: order_reference, customer_name, total, payment_method, coupons_applied, session_id, plus account_id, rule_code, anomaly_score (needed for coupon-velocity counting, audit and the dashboard). No phone/address hashes in the stored review.
- /settings/rulelock defaults to false when no row exists (the schema seeds false; the team's code defaulted to true).
- Simulations are excluded from /audit-log and /audit-log/latest (live reviews only), like the team's code.
- The c3 model is required for reviews but not for startup: a missing model makes /ready 503 and every review a hold.
- Event body limit 8 KB, review body limit 64 KB (413 as JSON).
- Dashboard cookie login (DASHBOARD_* env vars) removed: the monitor calls RuleLock from the shop server with the Bearer token.
- Dockerfile: python:3.11-slim, build context `rulelock/`, trains the model, non-root user, gunicorn 1 worker x 4 threads (Render free).
- `pytest` from `rulelock/` runs only the c1 tests; c2, c3 and c4 tests must run from their own folders (each has its own `app.py` and test module names would clash in one session).

## Known issues
- **supabase/schema.sql (Part 0) does not match the team's audit RPC yet.** c1 calls `record_rulelock_review(p_event jsonb, p_audit jsonb)` and the audit columns of `data-collection/migrations/2026-10-03_*.sql`; the stand-in in schema.sql has a different RPC signature and columns, so real reviews will hold with "could not be stored" until Part 0's section 3 is replaced by the team's three migrations. Part 0 and Part 1 are still `PARTIAL`.
- Never run against real Supabase or Docker; pinned scikit-learn 1.5.1 not tested.
- `scripts/purge_old_events.py` (retention) does not exist; nothing depends on it.
- Shop-side: the shop sends `address_hash`/`phone_hash` null when unknown; c1 handles that.

## Requests to other parts
- Part 0 / Part 7: replace the stand-in audit-log section of `supabase/schema.sql` with the team's three migrations (`data-collection/migrations/`): `2026-10-03_rulelock_audit_log.sql`, `..._review_idempotency.sql`, `..._backfill_order_reference.sql`. Keep `transaction_events.event_id` as uuid primary key. Then run it in a fresh project.
- Part 1 / Part 6 (shop): call `GET /audit-log/latest` (or `/audit-log/<order_reference>`) from the shop server with the Bearer token; the response has the full `pipeline`. Review requests should carry `order_id, order_reference, user_id, customer_name, session_id, device_id, phone_hash, address_hash, payment_method, items[{sku:"sku-<id>", quantity, unit_price}], coupons_applied, subtotal, discount_value, total` (the shop already does).
- Part 7: Render rulelock service: root directory `rulelock`, runtime Docker, env vars from `rulelock/.env.example`, health check path `/health`; set `RULELOCK_URL` in the shop to its public URL. `docker-compose.yml` already builds `./rulelock`.

## Next step (only if PARTIAL: exact file and function to continue from)
(not partial)
