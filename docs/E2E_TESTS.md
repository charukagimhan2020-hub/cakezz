# End-to-end tests (toggle OFF and ON)

Run these on the deployed Render shop (or on http://localhost:8080 with `docker compose up`). Each case says what to do, and what you must see with RuleLock OFF and ON. Nothing here needs Burp: everything is done with the browser dev tools Console.

## Before you start
1. Admin (`admin` / `admin123`) has added products: **Chocolate cake** price 3500 stock 50 and **Cupcakes** price 1200 stock 50.
2. Use **one browser window for the admin** (toggle + monitor + Admin > Orders) and **a separate Incognito/private window for each customer**. Why: RuleLock counts how many different accounts log in from one browser (the `device_id` cookie) in 24 hours. Two customers in the same browser look like account farming, and the second one gets blocked. A new Incognito window = a new device.
3. Where to look: **Admin > Orders** shows status, discount, total, coupons and the RuleLock decision and reason for every order. With RuleLock ON the dark **monitor tab** (`/monitor/`) shows the four steps.
4. Each account can use each coupon once (a used coupon is greyed out "already used"). Use a fresh account per case, or a different coupon.
5. Console tips: open dev tools (F12), tab **Console**, click the cart page first, paste the snippet, press Enter, then click **Place order**. If Chrome asks, type `allow pasting`. Always paste the snippet LAST (changing the quantity or a coupon afterwards recalculates the hidden fields).
6. Reset between rounds (Supabase SQL Editor; the audit log is insert-only and stays):
```sql
delete from account_restrictions;
delete from coupons_used;
delete from order_items;
delete from orders;
delete from transaction_events where event_type in ('LOGIN','BROWSE','ADD_TO_CART','APPLY_COUPON','CHECKOUT');
-- optional, removes all customer accounts: delete from users where role = 'customer';
```

## a. Normal customer, card order, one valid coupon: accepted both ways
Account `alice` (Incognito). Open the Chocolate cake, quantity 2, **Add to cart**. In the cart tick **CAKE20** (the other two grey out). Delivery address: anything. Payment: Card. **Place order**, on the payment page type anything and **Pay**.

| | OFF | ON |
|---|---|---|
| Result | order **COMPLETED**, total Rs 5,600 (7,000 - 20%) | the same: **COMPLETED**, total Rs 5,600, no warning message |
| Admin > Orders | RuleLock column empty | RuleLock `accept` |
| Monitor | (OFF page) | green **ACCEPTED**, step 2 PASS with every check ticked, step 3 NORMAL |
| Coupon | CAKE20 now greyed out "already used" in alice's cart | same |

## b. Normal customer, COD order: accepted both ways
Same account (`alice`, now verified because she has a COMPLETED order). One Chocolate cake, no coupon, address anything, Payment: **Cash on Delivery**, **Place order**.

| | OFF | ON |
|---|---|---|
| Result | order **PLACED** ("pay cash on delivery") | **PLACED**, no warning |
| Monitor | - | ACCEPTED; the COD order value and COD abuse checks are ticked |
A brand-new account with a COD order under Rs 15,000 is also accepted (the unverified cap only applies above Rs 15,000).

## c. Coupon stacking (CAKE50 + CAKE20 + CAKE10)
Account `bob` (Incognito), 2 x Chocolate cake in the cart, payment COD. Paste in the Console:
```js
document.querySelectorAll('.coupon-box').forEach(b => { b.disabled = false; b.checked = true; });
const sub = parseFloat(document.getElementById('f_sub').value);
document.getElementById('f_disc').value = (sub * 0.8).toFixed(2);
document.getElementById('f_total').value = (sub * 0.2).toFixed(2);
```
Click **Place order**.

| | OFF | ON |
|---|---|---|
| Result | order **PLACED** with an **80% discount**: Rs 7,000 becomes Rs 1,400 | page says "Your order continues at the full price"; order **PLACED at Rs 7,000**, discount 0 |
| Admin > Orders | discount 5,600, total 1,400, coupons CAKE50, CAKE20, CAKE10 | discount 0, total 7,000, coupons empty, RuleLock `void_discount` |
| Monitor | - | amber **DISCOUNT VOIDED**; red checks "Coupon usage" (3 stacked, max 1) and "Discount range"; the total check is ticked |

## d. Reusing an already used coupon
Account `carol`. First buy 1 cake with **CAKE10** normally (Card or COD) so CAKE10 becomes "already used". Then add a cake again: CAKE10 is greyed out. Paste:
```js
const b = document.querySelector('.coupon-box[value="CAKE10"]'); b.disabled = false; b.checked = true;
const sub = parseFloat(document.getElementById('f_sub').value);
document.getElementById('f_disc').value = (sub * 0.10).toFixed(2);
document.getElementById('f_total').value = (sub * 0.90).toFixed(2);
```
| | OFF | ON |
|---|---|---|
| Result | accepted with the 10% discount again | "Your order continues at the full price", total back to the catalog price |
| Monitor | - | DISCOUNT VOIDED; red "Coupon usage": "Coupon CAKE10 was already used by this account". Doing it more than 5 times in 24 h also trips "Coupon velocity" |

## e. Price tampering
Account `dave`, 2 x Chocolate cake, payment COD. Paste:
```js
document.querySelectorAll('input[name$="[unit_price]"]').forEach(i => i.value = '100');
document.getElementById('f_sub').value = '200';
document.getElementById('f_total').value = '200';
```
(Second variant: only change the total: `document.getElementById('f_total').value = '1';`.)

| | OFF | ON |
|---|---|---|
| Result | order **PLACED** for Rs 200 (or Rs 1) instead of Rs 7,000 | **BLOCKED**, message "Sorry, we could not process this order."; no order is placed |
| Admin > Orders | total 200 (or 1) | status BLOCKED, RuleLock `reject` |
| Monitor | - | red **BLOCKED**; red "Prices match catalog" (`supplied 100, catalog 3500`) and "Total matches catalog"; sentence "Blocked: Price mismatch: ...". Total-only variant: only "Total matches catalog" is red |

## f. Quantity abuse (0, -1, 9999)
Account `erin`, 1 Chocolate cake, payment COD. Paste one of the three values (change `'-1'` to `'0'` or `'9999'`). `noValidate` switches off the browser's own minimum check:
```js
document.getElementById('cartform').noValidate = true;
const q = document.querySelector('.qty'); q.value = '-1';
q.dispatchEvent(new Event('input'));
```
| | OFF | ON |
|---|---|---|
| Result | order accepted (**PLACED**) with quantity 0, -1 (a negative total!) or 9999 | **BLOCKED** for all three |
| Monitor | - | red "Quantity limit": `Quantity -1 for sku-1 is outside the allowed range 1 to 20` |

## g. Fake COD spam and an account farm
**Part 1: cancelled COD orders (history).** Account `frank` (Incognito). With RuleLock **OFF**: place a COD order (1 cake), go to **My orders**, click **Cancel**. Do it twice. (OFF: every order is accepted, no limit.) Also with account `gina` (new, never completed an order): one COD order of 5 x Chocolate cake (Rs 17,500): OFF: **PLACED**.

**Part 2: turn RuleLock ON.**
- `frank` (2 bad of 2 COD orders) places a COD order: **HELD** ("Your order is being reviewed..."). Monitor: HELD, red "COD abuse history: 2 of 2 previous COD orders were cancelled...".
- Turn OFF, `frank` places and cancels a third COD order, turn ON, he orders again: **BLOCKED** (reject). Monitor: red BLOCKED, COD abuse history 3 of 3.
- `gina` places the Rs 17,500 COD order: **HELD**. Monitor: red "COD order value: Unverified COD total 17500 exceeds the cap of 15000".

**Part 3: high anomaly score and the rate limit (RuleLock ON).** In ONE Incognito window log in and out as four different accounts (create `h1`, `h2`, `h3`, `h4`; log in as each). Then, as `h4`, place any normal card order.

| | OFF | ON |
|---|---|---|
| Result | accepted | **BLOCKED** even though every rule passes: "anomaly score indicates elevated risk" |
| Monitor | - | step 2 PASS, step 3 **HIGH RISK** (score about -0.11, 4 accounts on this device), step 4 BLOCKED with "Account rate limited for 30 minutes" |
| Next order of `h4` | accepted | red message on the cart page: "Your account is temporarily limited. You can try to check out again in about 30 minute(s)." (the row is in the Supabase table `account_restrictions`; delete it to continue testing) |

## h. Render cold start
1. RuleLock ON. Close the monitor tab (it keeps RuleLock awake) and do nothing for **20 minutes**, or in the Render dashboard open `rulelock` > Manage > Suspend, then Resume and immediately continue.
2. As a customer, do a normal checkout (as in a).
3. Expected: the checkout page may take 30 to 60 seconds. Then either the correct decision (payment page / order placed) or, if RuleLock needs longer than 60 seconds, the order status **HELD** with the message "Your order is being reviewed. We will contact you soon." (Admin > Orders RuleLock reason: "RuleLock did not answer in time ..."). **Never** an error page or a crash.
4. Try the same checkout again right away: normal fast answer.
5. Also test RuleLock being down: set a wrong `RULELOCK_URL` on the shop (or stop the container) and check out: **HELD** within a few seconds. Set it back.

## API-level version (no browser)
`BASE_URL=https://<your-rulelock>.onrender.com RULELOCK_API_TOKEN=<token> SKU=sku-1 PRICE=3500 ./scripts/smoke_test.sh` runs clean order, coupon stacking, price/quantity/total tampering, COD abuse and a coupon burst through `POST /review-order` with `"simulation": true` (no real orders are changed) and prints PASS/FAIL.
