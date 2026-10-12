# Risks and known issues

## Read this first
- **The shop is vulnerable on purpose.** With RuleLock OFF it trusts prices, totals, discounts, quantities and coupons from the browser. It must **never** hold real customer data, real card numbers, real passwords you use elsewhere, or run on a real domain. The fake payment page never reads or stores card input. Use made-up phone numbers and addresses.
- **Nothing here has been run end to end by the person who wrote the code.** The Python parts (c1 to c4) and the monitor's JavaScript have automated tests (see `README.md`). The PHP shop, the PHP monitor proxy, `schema.sql` in a real Supabase project, the Docker builds, and the Render deployment were written and checked statically only. Expect small fixes on the first real run; `docs/E2E_TESTS.md` is the checklist.

## Model and evaluation
- The Isolation Forest is trained on **synthetic** sessions and tested on synthetic abuse made with the same assumptions: the evaluation is **circular**. It shows the pipeline works, not real-world accuracy.
- To make the model separate the demo abuse the contamination setting was raised (0.03 to 0.13). Cost: about 8% of the broad normal mix is held and 6% rejected, mostly sessions with **two or more accounts on one device or two addresses on one phone** (a family sharing a laptop would be flagged). A reject also rate limits the account for 30 minutes.
- The model file is trained at Docker build with scikit-learn 1.5.1. The numbers in the README were measured with 1.8.0; re-run `python evaluate.py` after the first build.
- Features are only built from events the shop sends **while RuleLock is ON**. A session that starts before the toggle is switched ON has little history, so the anomaly step sees defaults.

## Hosting
- **Render free cold starts:** after 15 minutes idle a service takes 30 to 60 seconds to wake. The shop waits up to 60 seconds for RuleLock, then holds the order ("being reviewed"). Switch RuleLock ON 2 minutes before a demo (the shop pings `/health`), and keep the monitor open.
- **Supabase free projects pause after about a week without use.** Open the project (or run a query) before the presentation.
- Free RAM is about 512 MB: gunicorn runs 1 worker with 4 threads.
- One shared secret (`RULELOCK_API_TOKEN`) protects RuleLock; there is no per-client key, no request signing and no rate limit on RuleLock itself. The Supabase **secret** key has full access: keep it only in Render and local `.env` files, never in the repo or the browser.

## Behaviour to know about
- Two customers logged in from the same browser look like one device with two accounts and are blocked when RuleLock is ON (the admin is excluded). Use one Incognito window per customer in demos.
- Coupons are recorded as used only when an order is completed or placed with the discount intact. A held, blocked or voided order does not use up the coupon.
- Stock is shown but not reduced and not enforced by the shop.
- The delivery address is only hashed for RuleLock; it is not stored in the order.
- If RuleLock is switched OFF, its monitor tab shows the OFF state and stops reading orders; reviews already stored stay in the audit log.
- The audit log is insert-only by design: test data in it cannot be deleted from the app (use a new Supabase project to start completely clean). The reset SQL in `docs/E2E_TESTS.md` leaves it alone.
- Idempotency is per order id. A retry returns the stored review; two simultaneous first requests could both enforce once (a rate limit row could be written twice).
- If the shop cannot reach Supabase it shows a generic error page; if RuleLock cannot reach Supabase it answers `hold`.

## Not done / not verified
- `scripts/purge_old_events.py` (retention) mentioned in the team's old README never existed; there is no event retention.
- No browser test of the monitor layout; no PHP unit tests.
- `RULELOCK_MOCK` still exists in the shop and the monitor for local tests, but is ignored when `APP_ENV=production` or on Render.
- The team's backfill migration `2026-10-03_backfill_order_reference.sql` is not run (not needed on a fresh project).
