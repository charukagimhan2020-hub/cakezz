# Setup guide

Two programs, one database: the PHP shop (`shop/`), RuleLock (`rulelock/`, one Flask process) and Supabase (cloud). You need: a Supabase account, Docker (for the easy local run), and later a Render account.

## 1. Create the Supabase project (free)
1. supabase.com > **New project**. Pick a name and a database password (you will not need the password for the app).
2. Wait until the project is ready (1 to 2 minutes).

## 2. Make the admin password hash
The shop checks passwords with PHP, so the hash must be made by PHP. Run ONE of these and copy the line it prints (it starts with `$2y$`):
```
php -r 'echo password_hash("admin123", PASSWORD_DEFAULT), PHP_EOL;'
docker run --rm php:8.2-cli php -r 'echo password_hash("admin123", PASSWORD_DEFAULT), PHP_EOL;'
```
Open `supabase/schema.sql`, find `PASTE_PHP_HASH_HERE` (near the end) and replace it with that line. Keep the single quotes.

## 3. Run schema.sql
1. Supabase > **SQL Editor** > **New query**. Paste the whole `supabase/schema.sql`. Click **Run**. It must end with "Success".
2. It is safe to run again (for example after you paste the hash).
3. Check **Table Editor**: users, products, coupons (3 rows), orders, order_items, coupons_used, platform_settings (1 row, `rulelock_enabled` false), transaction_events, account_restrictions, rulelock_audit_log. `users` has `admin`.
4. Section 3 of the file is the team's own audit-log migration (insert-only audit table and the `record_rulelock_review` function). Do not edit it.

## 4. Find the URL and the secret key
Supabase **Project Settings > API**: Project URL = `SUPABASE_URL`. The **secret** (service_role) key = `SUPABASE_SECRET_KEY`. Never use the anon / publishable key. Never put the secret key in the repo or in the browser.
Make one long random string for `RULELOCK_API_TOKEN` (shop and RuleLock must have the SAME value):
```
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 5. Run everything on your computer (Docker)
```
cp .env.example .env        # then edit .env: SUPABASE_URL, SUPABASE_SECRET_KEY, RULELOCK_API_TOKEN (leave RULELOCK_MOCK=0)
docker compose up --build
```
- Shop: http://localhost:8080 (admin / admin123). RuleLock: http://localhost:5001/health (answers `{"status":"ok"}`) and http://localhost:5001/ready (200 when the model is loaded and Supabase answers).
- The first build trains the anomaly model (about a minute). Stop with Ctrl+C, `docker compose down`.
- Tune RuleLock rules by putting values from `rulelock/.env.example` into `rulelock/.env` (optional).
Then: log in as admin, **Admin > Products > Add product** (for example "Chocolate cake" price 3500 stock 50, and "Cupcakes" price 1200). Run the smoke test against RuleLock:
```
BASE_URL=http://localhost:5001 RULELOCK_API_TOKEN=<your token> SKU=sku-1 PRICE=3500 ./scripts/smoke_test.sh
```
(`sku-1` = the product with id 1; check the id in Supabase Table Editor if the first product you add is not id 1.)

### Without Docker
Shop (needs PHP 8.2 with curl): `cp shop/.env.example shop/.env`, fill it (`RULELOCK_URL=http://localhost:5001`), then `php -S localhost:8080 -t shop`.
RuleLock (Python 3.11): `cp rulelock/.env.example rulelock/.env`, fill it, then
```
cd rulelock/c1-data-collection && pip install -r requirements.txt
(cd ../c3-anomaly-detection && python train_model.py)
python app.py        # port 5001
```

## 6. Deploy on Render (two free Docker services)
The current `shop/` frontend is a PHP/Apache application with server-side sessions and database calls. GitHub Pages only serves static files, so it cannot host this frontend without a separate rewrite as a static JavaScript application. Deploy both `cakezz-shop` and `rulelock` through this Render Blueprint.

1. Push the repo to GitHub (the `.gitignore` already keeps `.env`, models and zips out).
2. Render > **New > Blueprint** > pick the repo. It reads `render.yaml` and creates `rulelock` and `cakezz-shop` (both free plan, Docker).
3. Render asks for the secret values. Enter them for **both** services where listed:

| Variable | `rulelock` | `cakezz-shop` | Value |
|---|---|---|---|
| SUPABASE_URL | yes | yes | your project URL |
| SUPABASE_SECRET_KEY | yes | yes | the secret key |
| RULELOCK_API_TOKEN | yes | yes | the SAME random string in both |
| RULELOCK_URL | - | yes | the public URL of `rulelock`, e.g. `https://rulelock-xxxx.onrender.com` (no trailing slash). You only know it after `rulelock` is created: leave it empty at first, then set it in the dashboard (Environment) and the shop redeploys |
| APP_ENV | production (set) | production (set) | makes RuleLock require the token and the shop ignore `RULELOCK_MOCK` |
| RULELOCK_MOCK | - | 0 (set) | ignored in production anyway |
| WEB_CONCURRENCY | 1 (set) | - | gunicorn workers; free plan has about 512 MB RAM |

4. Health checks (already in `render.yaml`): `rulelock` = `/health`, `cakezz-shop` = `/health.php`. Neither touches the database.
5. Open the shop URL, log in as admin, add products, run the end-to-end tests in `docs/E2E_TESTS.md`.
6. **Cold start.** Free services sleep after about 15 minutes idle; the first request takes 30 to 60 seconds. The shop waits up to 60 seconds for RuleLock and treats a timeout or error as `hold`. When the admin turns RuleLock ON, the shop calls `GET {RULELOCK_URL}/health` once to wake it, and the monitor tab keeps it awake. Before a presentation: turn the toggle ON 2 minutes early.

## 7. RuleLock settings (all optional, defaults shown; names are the same in every file)
| Setting | Default | Meaning |
|---|---|---|
| MAX_COUPONS | 1 | coupons per order |
| MAX_DISCOUNT_RATIO | 0.6 | discount over this share of the subtotal fails |
| MAX_QUANTITY_PER_LINE | 20 | quantity must be 1 to this |
| MIN_PURCHASE_AMOUNT | 500 | minimum subtotal when a coupon is used |
| PRICE_MATCH_TOLERANCE | 0.01 | unit price may differ from the catalog by 1 % |
| TOTAL_TOLERANCE | 1 | allowed difference of the recomputed total |
| COD_UNVERIFIED_ORDER_CAP | 15000 | COD over this from an account with no completed order = hold |
| COD_BAD_HOLD / COD_BAD_REJECT / COD_BAD_RATIO | 2 / 3 / 0.5 | bad COD orders for hold / reject, and the bad share |
| COUPON_VELOCITY_MAX_REVIEWS | 5 | coupon reviews per account in 24 h |
| ANOMALY_HOLD_THRESHOLD / ANOMALY_REJECT_THRESHOLD | -0.06 / -0.1 | anomaly score limits |
| RATE_LIMIT_MINUTES | 30 | account rate limit after an anomaly reject |
| MODEL_PATH | next to the code | anomaly model file |
| CORS_ORIGINS | empty (off) | the shop calls RuleLock from its server, so CORS stays off |
