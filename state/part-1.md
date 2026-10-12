Status: PARTIAL
Part: 1
Last session: 2026-10-11

## Done (short)
All of Part 1 is written: customer side (signup, login, logout, catalog, product page, cart with coupon picker, checkout, fake payment, my orders + cancel), admin side (products, orders, RuleLock toggle), toggle OFF vulnerable path, toggle ON review flow, `/events`, `RULELOCK_MOCK`, Supabase REST helper, Dockerfile, banner, `shop/TESTING.md`.
Part 0 was not DONE when this ran (see state/part-0.md); this session continued anyway because the missing migrations do not affect the shop code.

## Files created or changed
shop/: Dockerfile, .dockerignore, README.md, TESTING.md, index.php, product.php, signup.php, login.php, logout.php, cart.php, checkout.php, payment.php, order_result.php, orders.php, cancel_order.php, admin/{index,toggle,products,product_form,orders}.php, includes/{init,db,rulelock,lib,layout,admin_layout}.php, assets/style.css, assets/products/placeholder.svg

## Interfaces (exact function signatures / endpoints / tables touched)
- Shop to RuleLock: `POST {RULELOCK_URL}/review-order` (Bearer, 60 s) with raw browser values, exactly as CONTRACT.md. `POST /events` (2 s timeout, errors ignored) for LOGIN, BROWSE, ADD_TO_CART, APPLY_COUPON, CHECKOUT. `GET /health` once when the admin turns the toggle ON.
- Shop writes: users, orders (status, rulelock_decision, rulelock_reason, coupons_applied, cancelled_by), order_items, coupons_used, platform_settings. Reads: products, coupons, account_restrictions.
- Order flow: toggle OFF card = PENDING then COMPLETED on the payment page; OFF COD = PLACED at once. Toggle ON: PENDING, then accept/void_discount continue (Card pays, COD = PLACED), hold = HELD, reject = BLOCKED, timeout/error/unknown = HELD.
- On void_discount the shop trusts RuleLock (c4) to have recomputed `orders.subtotal/discount_value/total`, then reloads the order and sets `coupons_applied = []`.
- Mock: `RULELOCK_MOCK=1`, add `?mock=accept|void_discount|hold|reject` to `/cart.php`. The mock void_discount recomputes the total from the catalog like c4 should.

## Env vars (name, meaning, default)
SUPABASE_URL, SUPABASE_SECRET_KEY, RULELOCK_URL, RULELOCK_API_TOKEN, RULELOCK_MOCK (0), PORT (Docker, default 80).

## How to run and test (and the test result you actually saw)
NOT RUN. This sandbox has no PHP, no Docker, no network. Only a brace/bracket balance check over all PHP files was done (it passed). Follow `shop/TESTING.md`; first run `php -l` on every file (`find shop -name '*.php' -exec php -l {} \;`).

## Kept / changed / why (reused teammate code)
None (no teammate code needed for this part).

## Decisions (anything you chose because the brief was unclear)
- Extra CSRF token on every form (so CSRF is not an unlisted vulnerability). Logout is POST.
- Cart lives in the PHP session. Visible quantity box and hidden `unit_price`, `subtotal`, `discount_value`, `total` fields are plain form fields. Coupon rows are recorded in `coupons_used` only when an order is completed/placed (not when held, blocked or discount voided), and without checking `coupons_used` first.
- Delivery address is asked at checkout, only hashed (sha256 of lower-case text), not stored (no column in the brief). Phone hash comes from the phone given at signup.
- Stock is shown but not decremented, and not enforced on the server.
- Rate-limit check only runs while the toggle is ON.
- `address_hash` / `phone_hash` are sent as null in `/events` when unknown.
- Order number is `CZ-` + UTC `YmdHis`; on a clash it appends `-NN`.
- Admins cannot add to cart or buy. Admin removing an order deletes its items (cascade).
- Apache listens on `$PORT` (Render) with default 80.

## Known issues
- UPDATE by Part 7: RULELOCK_MOCK is now ignored when APP_ENV=production or on Render; no events are sent for the admin; `health.php`, `APP_ENV` in the Dockerfile and in `.env.example` were added. Still never run in PHP.
- Never executed: expect small typos until `php -l` and the checklist are run.
- `/monitor/` does not exist until Part 6 (the toggle tab shows a 404).
- No products exist after setup; add them in Admin > Products.

## Requests to other parts
- Part 4 (c4): on void_discount, recompute `orders.subtotal`, `discount_value`, `total` from the catalog (the shop reloads them). The shop also sets HELD/BLOCKED itself, harmless if c4 does it too.
- Part 5 (c1): `/review-order` must answer HTTP 200 with the contract shape; the shop treats anything else as hold.

## Next step (only if PARTIAL: exact file and function to continue from)
Run `php -l` on all files and the checklist in `shop/TESTING.md` on a machine with PHP + Supabase. Fix any error, then change line 1 of this file to `Status: DONE`.
