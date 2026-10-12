# c1-data-collection (Charuka) - the RuleLock backend

ONE Flask process (`app.py`). It imports c2 (rules), c3 (anomaly model) and c4 (decision + enforcement) as plain Python modules, so Render free only has to wake one service.

## Endpoints
All need `Authorization: Bearer <RULELOCK_API_TOKEN>` except `/health` and `/ready`.
| endpoint | what it does |
|---|---|
| `POST /events` | store one shopper event (`LOGIN BROWSE ADD_TO_CART APPLY_COUPON CHECKOUT`) in `transaction_events`. Body: `event_type, session_id` (required), `user_id, device_id, phone_hash, address_hash, metadata`. `session_id`, `device_id`, `phone_hash`, `address_hash` (and `account_id` = user_id) are stored inside `metadata`. 201 on success, 400 for a bad or unknown event, 413 over 8 KB, 503 if the database fails |
| `POST /review-order` | review one order (CONTRACT.md). Always HTTP 200 when the review ran. Idempotent per `order_id`: a second call returns the stored review and changes nothing |
| `GET /audit-log` | list of reviews (filters `action`, `search`, `cursor`, `limit`) |
| `GET /audit-log/latest` | newest live review with its full `pipeline` (the monitor tab polls this). 404 when there is none |
| `GET /audit-log/<order_id_or_reference>` | full stored review with `pipeline` for one order, by number or by `CZ-...` reference |
| `GET /dashboard/summary` | 24 h numbers built from the audit table |
| `GET` / `POST /settings/rulelock` | read or set `platform_settings.rulelock_enabled` (default false when no row) |
| `GET /pipeline/info` | model metadata, rule settings, enforcement thresholds |
| `GET /health` | liveness, no auth, no database |
| `GET /ready` | 200 only when the model is loaded AND Supabase answers, else 503 |

## The review flow (`pipeline.py`)
1. **c1** reads the catalog, the coupon table, the account profile, the account's earlier COD orders, the coupon-review count of the last 24 h, and builds the session features from `transaction_events`.
2. **c2** `validate_transaction(payload, catalog, coupon_review_count, coupon_percents)`. The payload is the request body as the shop sent it (browser values untouched) plus four fields from our own data: `account_verified` (at least one COMPLETED order), `past_orders`, `past_refusals` (bad COD = REFUSED, or CANCELLED by the customer), `used_coupons` (codes from `coupons_used`, so a reused coupon fails `coupon_usage`). A value for these four sent in the request is overwritten.
3. **c3** `score_session(features)`.
4. **c4** `decide(...)` then `apply_enforcement(...)` (real writes: order HELD / BLOCKED / discount voided, `account_restrictions` row). `adapter.py` gives c4 its `db` object.
5. The `pipeline` object is built as in the contract and stored with the order context (`order_reference, customer_name, total, payment_method, coupons_applied, session_id`, plus `account_id`, `rule_code`, `anomaly_score`) in one atomic RPC (`record_rulelock_review`: transaction event + immutable audit row).
`"simulation": true` runs the same pipeline without changing orders or accounts, stores it as `RULELOCK_SIMULATION`, and takes the account history from `simulated_account` (`cod_orders, cod_bad, completed_orders, coupon_reviews_24h`).

**Fail safe.** Every step is wrapped. A failing step gets `status: "error"` and an `error` text in `pipeline`; if the decision would have been accept or void_discount it becomes `hold`. A rule reject stays a reject. If the order cannot be changed in the database the result is hold. If the review cannot be stored: hold (a reject stays reject).

## Session features (what is counted)
| feature | counting |
|---|---|
| `coupon_attempts_per_session` | `APPLY_COUPON` events with this `session_id` in the last 30 minutes |
| `avg_seconds_between_requests` | all events of the session in the last 30 minutes: (last - first) / (n - 1); 30 if fewer than 3 events |
| `distinct_accounts_same_device` | different `user_id` on events with this `device_id` in the last 24 h (at least 1) |
| `distinct_addresses_same_phone` | different `address_hash` on events with this `phone_hash` in the last 24 h (at least 1) |
`device_id` and `phone_hash` fall back to the values found in the session's events. The shop sends `APPLY_COUPON` once per coupon at checkout; the review itself is not counted.

## Settings
One name per setting: see `../.env.example`. Auth fails closed: with no `RULELOCK_API_TOKEN` every protected call is 401 unless `RULELOCK_ALLOW_NO_AUTH=1` (local only). With `APP_ENV=production` (the Docker image) the app refuses to start without a token. CORS is off unless `CORS_ORIGINS` is set. No Supabase URL is hard-coded.

## Layout
`app.py` (Flask app, /health, /ready) - `paths.py` (puts c2, c3, c4 on sys.path) - `config.py` - `db.py` (Supabase REST) - `adapter.py` (c4's db interface) - `pipeline.py` (orchestrator) - `routes/events.py` (all other endpoints) - `tests/`.

## Run and test
`pip install -r requirements.txt`, set `.env`, then `python train_model.py` inside `../c3-anomaly-detection`, then `python app.py` (port 5001) or `gunicorn app:app`. Tests: `pytest` inside this folder (or from `rulelock/`): 49 tests with the real c2, c3, c4 and an in-memory fake database (the model is trained into a temp file). Demo attacks against a running instance: `scripts/smoke_test.sh`. Docker: `docker build ./rulelock` (the image trains the model, runs gunicorn with 1 worker and 4 threads).

## Changes from the team's `data-collection/` folder
- Deleted the copies of `rules.py`, `decision.py`, `actions.py`, `features.py`, `train_model.py`, `synthetic_data.py`, `evaluate.py`, `anomaly_scoring.py`, `services/forwarder.py`, the demo `static/` storefront, `schema.sql`, `catalog.py` (the catalog now comes from the `products` table), the dashboard cookie login and its env vars, the old retention test (it needs `scripts/purge_old_events.py`, which was never in the zip).
- New: `POST /events`, `GET /audit-log/latest`, `pipeline.py`, `adapter.py`, `paths.py`, size limits, `/ready` checks the model file.
- `/review-order` no longer forwards to another service: it runs c2, c3, c4 in process. The old response extras (`rule_result`, `anomaly_result`, `enforcement_result`) are gone; the response is exactly the contract.
- The audit row is built by c4's `build_audit_payload`. Coupon-review counts and COD history are read live from Supabase (the old code did too).
- Fixed: a `None` row in the event lists crashed the feature counting; a failing database read used to be hidden in some paths (now a hold).
