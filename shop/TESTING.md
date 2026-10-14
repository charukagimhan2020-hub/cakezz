# Shop test checklist (Part 1)

Setup: run `supabase/schema.sql` (with the admin hash pasted), fill `shop/.env`, start the shop. For the fake RuleLock set `RULELOCK_MOCK=1`.
Mock mode: add `?mock=accept|void_discount|hold|reject` to the cart URL, e.g. `/cart.php?mock=hold`. The checkout then uses that answer. Default is accept.

## A. Toggle OFF (default)
1. Home page shows the yellow banner. No cakes yet is fine.
2. Log in as `admin` / `admin123`. Admin > Products > Add product (name, price 3500, stock 10, image `placeholder.svg`). Add a second one.
3. Log out. Sign up as `kamal` (any password of 6+ characters, any phone). Log in.
4. Logged out: product page shows "Log in to buy" and no buttons.
5. Product page: set quantity 2, **Add to cart**. Cart shows the line and total. Change quantity, **Update cart**. **Remove** a line.
6. Coupons: tick CAKE20, the other two grey out and cannot be clicked. Untick, they come back. Total and discount change.
7. Card order: address "any", Card, **Place order**. Fake payment page opens. Type anything (or nothing), **Pay**. Order shows COMPLETED. Cart is empty.
8. COD order: choose COD, **Place order**. Order PLACED. My orders > **Cancel** it: status CANCELLED. (Supabase: `cancelled_by = CUSTOMER`.)
9. Coupon used in step 7 is now greyed out "(already used)" in the cart.
10. Coupon lock (front end only): as `kamal`, buy once with CAKE20 (Card or COD). In every later cart CAKE20 is greyed "already used"; CAKE50 and CAKE10 are still free until used; ticking one of them greys out the other two. Log in as another account: all three are free again.
11. OFF refuses nothing: leave the address empty and Place order: it goes through. In the Console set a quantity box to -1 (no browser minimum any more) or paste a product id that does not exist (`document.querySelector('input[name$="[product_id]"]').value = 99999`): the order is still created (an unknown product is stored as empty).
12. Vulnerabilities (dev tools, Elements): edit the hidden `unit_price`, `subtotal`, `discount_value`, `total`, set quantity to 0, -3 or 99999, tick two coupons by removing `disabled`, reuse a used coupon, place many COD orders. All of them must go through with the toggle OFF.
13. Admin > Orders lists the orders (with the tampered values) and **Remove** deletes one. No approve/review buttons.

## B. Toggle ON (with the mock)
1. Admin > **Turn RuleLock AI ON**. A new tab opens the dark RuleLock monitor at `/monitor/`. The admin page says ON.
2. `/cart.php?mock=accept`: Card order goes to payment; COD order becomes PLACED. Order row has `rulelock_decision = accept`.
3. `/cart.php?mock=void_discount` with a coupon: message "Your order continues at the full price"; total is the catalog price without discount; order continues.
4. `/cart.php?mock=hold`: status HELD, message shown, no payment page.
5. `/cart.php?mock=reject`: status BLOCKED, message shown, no payment page.
6. Real RuleLock down (`RULELOCK_MOCK=0`, wrong URL): after the wait the order is HELD.
7. Rate limit: in Supabase insert into `account_restrictions` (user_id of kamal, type `rate_limit`, until = a time 10 minutes ahead). Checkout now refuses and shows the minutes left.
8. Turn it OFF again: the vulnerable path works again right away (the toggle is read on every checkout).
