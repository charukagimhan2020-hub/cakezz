Status: PARTIAL
Part: 7
Last session: 2026-10-11

## Done (short)
Integration check of the whole repo (new `scripts/check_integration.py`, 41 checks, all pass), real fixes for the mismatches it and a manual walk-through found, local `docker compose`, `render.yaml`, end-to-end test steps, demo script, viva answers, risk list, top-level README, final checklist below.
PARTIAL because the parts that need PHP, a real Supabase project, Docker and Render were only checked statically; Parts 0, 1 and 6 are also still PARTIAL for the same reason. Nothing was run end to end.

## Files created or changed
Created: README.md (rewritten), render.yaml, .env.example, docs/{SETUP (rewritten), E2E_TESTS, DEMO, VIVA, RISKS}.md, scripts/check_integration.py, shop/health.php, shop/.env.example (rewritten), state/part-7.md.
Changed (outside Part 7's own files; every change logged here):
- supabase/schema.sql (Part 0): section 3 replaced by the team's migrations 1 and 2 (unchanged); migration 3 (backfill) deliberately not run.
- docker-compose.yml (Part 0): both services start with `docker compose up` (no profile), one root `.env`, shop `APP_ENV=development`.
- shop/includes/rulelock.php (Part 1): `is_production()`; `rl_mock_on()` is false in production or on Render; `rl_event()` sends nothing for the admin.
- shop/Dockerfile (Part 1): `ENV APP_ENV=production`.
- shop/TESTING.md (Part 1): outdated 404 note about /monitor/ removed.
- rulelock/c2-rule-engine/rules.py + tests/test_rules.py + README.md (Part 2): `coupon_usage` also fails when a coupon was already used by the account (`used_coupons` in the payload, code stays `coupon_usage`, action void_discount). 25 tests.
- rulelock/c1-data-collection/db.py, pipeline.py, tests/c1_helpers.py, tests/test_review_flow.py, tests/test_features_and_db.py, README.md (Part 5): `get_used_coupons`, passed to c2 as `used_coupons` (also `simulated_account.used_coupons`). 50 tests (22 + 16 + 12).
- scripts/smoke_test.sh (Part 5): added the coupon-reuse check.
- state/part-0.md, state/part-1.md: one UPDATE line each in Known issues.

## Integration check: mismatches found and what was done
1. Part 0 schema had a stand-in audit RPC with another signature and columns than c1/c4 use -> replaced with the team's migrations (fixed).
2. Coupon reuse (demo case d, brief vulnerability 3) was not caught by any rule unless 6+ reviews in 24 h -> reuse check added inside `coupon_usage` (fixed; no new rule code, contract unchanged).
3. `RULELOCK_MOCK` could be on in production -> ignored in production / on Render (fixed). c1 never had a mock.
4. Compose ran RuleLock only with a profile, needed two env files -> one `docker compose up`, one root `.env` (fixed).
5. `rulelock/.env.example` and SETUP.md env tables used old names in SETUP.md -> SETUP.md rewritten; the checker fails if an old name comes back (fixed).
6. The shop sent events for the admin, so an admin browsing in the same browser counted as a second account on the device -> admin excluded (fixed). Customers in one browser still count (by design, documented in the demo and E2E docs).
7. Render needs a health path for the shop -> `shop/health.php` (added).
Verified consistent by the checker: all tables and selected columns used by PHP and c1 exist; order columns written by shop and c4; status values; shop payload fields = contract request; c1 response keys = contract response; pipeline step names; payment_action values; c2 and c4 rule maps equal and include total_mismatch; every RuleLock URL the shop and monitor call exists; env variable names documented once; render.yaml / compose structure.
Not changed (small, judged fine): c4's `apply_enforcement(result, order_id, account_id, db, payment_method=None)` differs from the contract text `apply_enforcement(result, order_id, account_id)` by the injected `db` argument (asked for in Part 4); the shop handles `hold_cod_order`/`hold_order` only as c4 labels.

## Interfaces (exact function signatures / endpoints / tables touched)
Unchanged from Parts 1 to 6, plus: `GET /health.php` on the shop (no database), `check_integration.py` (exit 1 on any mismatch). c2 payload gains optional `used_coupons`.

## Env vars (name, meaning, default)
One list per place: `.env.example` (compose), `shop/.env.example`, `rulelock/.env.example`, `docs/SETUP.md` tables, `render.yaml`. New: shop `APP_ENV` (production in the image).

## How to run and test (and the test result you actually saw)
Ran in this sandbox (no PHP, no Docker, no Postgres, no network, no pytest, plain-Python runner): c1 50 passed, c2 25, c3 15, c4 25, monitor JS 9 + 11, `check_integration.py` 41 of 41, `smoke_test.sh` over HTTP against the real Flask app with a fake database (every check passes except `/ready`, which needs Supabase). Brace check of all 25 PHP files passed. NOT run: PHP anything, `schema.sql`, Docker builds, gunicorn, Render, the whole flow.

## Kept / changed / why (reused teammate code)
Team migrations used unchanged. Everything else as in Parts 2 to 5.

## Decisions (anything you chose because the brief was unclear)
- Coupon reuse is checked inside `coupon_usage` (not a new rule) so CONTRACT.md and c4's rule map stay valid.
- One root `.env` for compose (shared token), `rulelock/.env` optional for tuning.
- render.yaml asks for secrets in the dashboard (`sync: false`) instead of env groups; `RULELOCK_URL` is typed in after the first deploy. Public URL used (not Render's private network) because sleeping services may not wake on private calls.
- The end-to-end steps are in `docs/E2E_TESTS.md` (the brief did not name a file); DEMO, VIVA and RISKS as asked.
- Demo accounts: one Incognito window per customer (device cookie), documented everywhere.
- The team's backfill migration is not part of `schema.sql` (it would hit the insert-only trigger).

## Known issues
- See docs/RISKS.md. Biggest: nothing run end to end; Parts 0, 1, 6 PARTIAL (unrun SQL, PHP, monitor proxy); synthetic and circular model evaluation; 8% hold / 6% reject on the broad normal mix; Render cold start; Supabase free pauses after a week.
- `scripts/check_repo.py --need 7` stops (Parts 0, 1, 6 not DONE); this session continued on request, as in Parts 2 to 6.
- The e2e Console snippets and UI steps were written from reading the shop code, not tried in a browser.

## Requests to other parts
None (last part).

## Final checklist
DONE (written, and checked automatically where possible):
- [x] c2 rule engine (25 tests), c3 anomaly detection (15), c4 enforcement (25), c1 orchestrator (50), monitor JS (20), integration checker (41)
- [x] contract: request, response, pipeline, decisions, payment actions, rule map all agree across shop, c1 to c4, schema
- [x] schema with the team's audit log, RLS, seeds; no card data stored; no checks that block tampered values
- [x] docker-compose (one command), render.yaml (two free services), health checks, wake-up on toggle ON
- [x] RULELOCK_MOCK off in production
- [x] docs: SETUP, E2E_TESTS (cases a to h), DEMO (8 min), VIVA, RISKS, README, per-component READMEs
NOT DONE / NOT VERIFIED (do these next, in this order):
- [ ] Run `supabase/schema.sql` in a fresh Supabase project (paste the admin hash first). Then set Part 0 to DONE.
- [ ] `docker compose up --build`; fix any PHP or Docker error (no PHP file was ever executed). Then run `shop/TESTING.md`; set Part 1 to DONE.
- [ ] `shop/monitor/TESTING.md` in a browser (RULELOCK_MOCK=1 locally first); set Part 6 to DONE.
- [ ] `python scripts/check_integration.py`, `pytest` in each folder with the pinned versions, `python evaluate.py` in c3 after the Docker build.
- [ ] Deploy with `render.yaml`; run `docs/E2E_TESTS.md` cases a to h with RuleLock OFF and ON; run `scripts/smoke_test.sh` against Render.
- [ ] Rehearse `docs/DEMO.md` once with a timer; reset data with the SQL in `docs/E2E_TESTS.md`.
- [ ] When all pass, change line 1 of this file to `Status: DONE`.

## Next step (only if PARTIAL: exact file and function to continue from)
First item of the NOT DONE list above: run `supabase/schema.sql` in a fresh Supabase project.
