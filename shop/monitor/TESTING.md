# Monitor test checklist (Part 6)

The monitor is `shop/monitor/`: `index.php` (page), `api.php` (server-side proxy, adds the RuleLock token), `monitor.js`, `monitor-logic.js`, `monitor.css`, `mock.json`.
It only observes: no button changes anything.

## Automatic checks (no browser, no PHP needed)
```
cd shop/monitor
node tests/logic.test.js     # sentences, labels, score bar position, mock.json shape
node tests/render.test.js    # renders the page script against a small fake DOM: 4 decisions, OFF, down, waiting, errors, XSS, history
```
Not covered by these (needs PHP and a browser): `api.php`, `index.php`, the real look. Do the manual checklist below.

## Manual checklist
Setup A (no RuleLock yet): `RULELOCK_MOCK=1` in `shop/.env`, start the shop, log in as `admin` / `admin123`, Admin > Turn RuleLock AI ON. A new tab opens `/monitor/`. The page says "MOCK DATA"; a new sample order appears every 12 seconds, cycling accept, void_discount, hold, reject. Pin one with `/monitor/?i=0` (accept), `?i=1` (void), `?i=2` (hold), `?i=3` (reject).
Setup B (real): `RULELOCK_MOCK=0`, `RULELOCK_URL` and `RULELOCK_API_TOKEN` set (same token as RuleLock), place orders in the shop with the toggle ON.

1. **Access.** Open `/monitor/` logged out: you are sent to the login page. Log in as a customer: "Admin only" (403). Open `/monitor/api.php?r=poll` logged out: JSON `login required` (401). View the page source and the network tab: the RuleLock token never appears.
2. **Accept.** Green ACCEPTED badge; step 2 says PASS with every check ticked; step 3 bar marker is in the green zone, label NORMAL; sentence "Accepted: all ... rule checks passed ...".
3. **Discount voided.** Amber DISCOUNT VOIDED; two failed checks (coupon usage, discount range) in red with their reason; the sentence says the order continues at the full catalog price.
4. **Held.** Orange HELD; the COD order value check is red; action `hold_cod_order`.
5. **Blocked.** Red BLOCKED; price mismatch and total mismatch are red; sentence "Blocked: Price mismatch: sku-1: supplied 100, catalog 3500."; in the real setup an anomaly block also shows "Account rate limited for 30 minutes".
6. **Animation.** When a new order arrives the four cards (and arrows) light up one after another (about 300 ms per step). Not on the first load of the page.
7. **History.** Table of up to 20 reviews, newest first; the selected row is marked. Click an older row: that order is loaded into the pipeline and "Back to the latest order" appears; when a new order arrives the view jumps to it. Tab or keyboard: Enter on a row opens it.
8. **Top bar.** Green light and "RuleLock online". Toggle pill shows ON. The three counters (reviewed, blocked/held, discounts voided) show numbers within about 10 seconds.
9. **OFF state.** Admin > Turn RuleLock AI OFF (in the other tab). Within 2 seconds the monitor shows "RuleLock is OFF - shop is vulnerable", the pill says OFF, the light is grey, and no orders are shown. Turn it ON again: orders return.
10. **RuleLock down.** Real setup: stop RuleLock (or set a wrong `RULELOCK_URL`). A red banner "RuleLock is not reachable: ..." appears, the light is red, the last data stays visible but dimmed. A wrong token gives "RuleLock refused the token". Start it again: the banner goes away by itself. (Render free: the first request after 15 minutes idle takes up to a minute; the banner may show while it wakes up.)
11. **Step failure.** (Real setup, for example with `MODEL_PATH` pointing to a missing file.) Step 3 shows its error text in red, the decision is HELD, the sentence starts "Held for safety".
12. **No orders yet.** With no reviews, the page says "Waiting for orders...".
13. **Hidden tab pauses.** Open the browser network tab, switch to another tab for 10 seconds: no new `api.php` calls until you come back; polling resumes at once.
14. **Screens.** Laptop (1366 x 768): four cards in a row, text readable from a distance. Narrow the window to about 1100 px: 2 x 2 cards; to 400 px (phone): single column, history rows become small cards. No horizontal scroll bar at any width.
