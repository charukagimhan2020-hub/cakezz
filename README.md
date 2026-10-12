# Cakezz + RuleLock AI

**RuleLock AI** is a university project that detects business-logic abuse in online shops: stacked or reused coupons, tampered prices and totals, impossible quantities, fake cash-on-delivery orders and account farming. **Cakezz** is a small PHP cake shop built to be vulnerable on purpose, so the attacks can be shown with RuleLock OFF and stopped with RuleLock ON. Every shop page carries the banner "Intentionally vulnerable demo - do not use real data".

How it works: with the admin toggle ON, every checkout goes to RuleLock. Four components run in one Flask process: **c1** collects the data and orchestrates, **c2** checks the business rules, **c3** scores how unusual the session is (Isolation Forest), **c4** decides (accept, void discount, hold, reject) and really changes the order. A dark **monitor** tab shows the four steps live. The contract between shop and RuleLock is `CONTRACT.md`.

## Folder map
| Folder | What | Owner |
|---|---|---|
| `shop/` | PHP shop (light theme), admin, fake payment page | project owner |
| `shop/monitor/` | RuleLock monitor tab (dark): PHP proxy, JS, CSS | project owner |
| `rulelock/c1-data-collection/` | Flask app: `/events`, `/review-order`, audit APIs, Supabase access, orchestration | Charuka |
| `rulelock/c2-rule-engine/` | business rules (coupons, prices, totals, quantity, COD) | Sadini |
| `rulelock/c3-anomaly-detection/` | Isolation Forest scoring, synthetic data, evaluation | Nihara |
| `rulelock/c4-enforcement-engine/` | decision policy, real order actions, audit payload | Mishen |
| `supabase/schema.sql` | all tables, audit log, RLS, seed data | - |
| `docs/` | `SETUP.md`, `E2E_TESTS.md`, `DEMO.md`, `VIVA.md`, `RISKS.md`, `BRIEF.md` | - |
| `scripts/` | `smoke_test.sh`, `check_integration.py`, `check_repo.py`, `pack.py` | - |
| `state/`, `STATE.md` | progress notes of each build session (what is done, decisions, known issues) | - |
`docker-compose.yml` runs both services locally, `render.yaml` deploys them to Render.

## Setup (short; full steps in `docs/SETUP.md`)
1. Create a Supabase project, paste the PHP hash of `admin123` into `supabase/schema.sql` (command in `docs/SETUP.md`), run the whole file in the SQL Editor.
2. `cp .env.example .env` and fill `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `RULELOCK_API_TOKEN`.

## Run
```
docker compose up --build
```
Shop http://localhost:8080 (admin / admin123), RuleLock http://localhost:5001/health. Add products in Admin > Products, then follow `docs/E2E_TESTS.md`.

## Test
| What | Command |
|---|---|
| c1 (49+ tests, real c2/c3/c4, fake database) | `cd rulelock/c1-data-collection && pytest` |
| c2 rule engine | `cd rulelock/c2-rule-engine && pytest` |
| c3 anomaly detection (trains a model first) | `cd rulelock/c3-anomaly-detection && python train_model.py && pytest` |
| c4 enforcement | `cd rulelock/c4-enforcement-engine && pytest` |
| monitor JavaScript | `cd shop/monitor && node tests/logic.test.js && node tests/render.test.js` |
| code, schema, env and deploy files agree | `python scripts/check_integration.py` |
| the demo attacks against a running RuleLock | `BASE_URL=http://localhost:5001 RULELOCK_API_TOKEN=... ./scripts/smoke_test.sh` |
| the PHP shop and the whole flow | by hand: `shop/TESTING.md`, `docs/E2E_TESTS.md` |
Run each Python folder's tests from inside that folder (each has its own `app.py` and test files). The PHP shop and monitor proxy have no automated tests.

## Deploy
`render.yaml` is a Render Blueprint for two free Docker services (`rulelock`, `cakezz-shop`). The current frontend is the server-rendered PHP app in `shop/`, so it must run on Render (or another PHP host); GitHub Pages cannot run this frontend. Steps, the environment variable table and the cold-start notes are in `docs/SETUP.md` (section 6). Set the same `RULELOCK_API_TOKEN` on both and `RULELOCK_URL` on the shop.

## Demo and viva
`docs/DEMO.md` (8-minute script), `docs/VIVA.md` (questions and answers), `docs/RISKS.md` (limits). Short version of the limits: the anomaly model is trained on synthetic data and evaluated circularly; Render free services sleep; the shop is vulnerable on purpose and must never hold real data.
