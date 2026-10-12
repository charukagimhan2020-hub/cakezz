# Demo script for the November presentation (about 8 minutes)

## 30 minutes before
- Render: both services deployed and awake (open `https://<shop>/health.php` and `https://<rulelock>/health`). Turn RuleLock ON, wait for the dark tab, then turn it OFF again. This wakes RuleLock; the free plan sleeps after 15 minutes idle.
- Supabase: run the reset SQL from `docs/E2E_TESTS.md` (clean orders, no used coupons). Products: Chocolate cake 3500, Cupcakes 1200.
- Windows: (1) **admin window**: logged in, Admin page open, a second tab on Admin > Orders. (2) **three Incognito windows**: `bob` (attack c), `dave` (attack e), `frank` (attack g) already signed up and logged in. Never log two customers into the same window.
- `frank` and `gina`: do the cancelled COD orders for attack g beforehand (OFF): `frank` has 2 cancelled COD orders. `gina` is a new account.
- Browser zoom 125%, dev tools ready in each Incognito window (Console tab). Keep the snippets from `docs/E2E_TESTS.md` in a text file.
- Plan B if the network or Render is down: run locally with `docker compose up` or, for the monitor only, `RULELOCK_MOCK=1` with `APP_ENV=development` and open `/monitor/?i=3`.

## The script
**0:00 Intro (45 s).** "Online shops check passwords and card numbers, but not the business rules: one coupon per order, the price from the catalog, a sensible quantity. RuleLock AI checks those rules, and learns what abnormal behaviour looks like. This is Cakezz, a cake shop we built to be vulnerable on purpose (point at the yellow banner). RuleLock has four parts, each built by a team member: Data Collection, Rule Engine, Anomaly Detection, Enforcement."

**0:45 Shop with RuleLock OFF (45 s).** Admin page: "RuleLock is OFF. The shop trusts whatever the browser sends." Open the shop in `bob`'s window, add 2 cakes: "A normal order works: Rs 7,000."

**1:30 Three attacks, RuleLock OFF (2 min).** Use the Console snippets, run each, show Admin > Orders after.
1. **Coupon stacking** (`bob`): "The page only allows one coupon, but the server doesn't check." Snippet c, Place order. Admin > Orders: "Rs 7,000 bought for Rs 1,400, 80% off."
2. **Price tampering** (`dave`): "I change the hidden price and total." Snippet e. Admin > Orders: "Same cakes for Rs 200."
3. **Fake COD spam** (`frank`): "This account placed and cancelled COD orders, and nothing stops him." Place another COD order: accepted. Show My orders with the cancelled orders. (Optional: `gina` with the Rs 17,500 COD order, also accepted.)
"All three succeeded. This is what a real shop loses."

**3:30 Switch RuleLock ON (45 s).** Admin page > **Turn RuleLock AI ON**. "A new tab opens: the RuleLock monitor." Drag it to the projector. Explain the four cards left to right: "1 Transaction Monitor collects what the shopper did and the account's history. 2 Rule Engine checks the business rules. 3 Anomaly Detection scores how unusual the behaviour is. 4 Enforcement decides: accept, void the discount, hold, or block, and really changes the order."

**4:15 The same attacks, RuleLock ON (3 min).** After each attack point at the monitor; the four cards light up one after another.
1. **Stacking** (`bob`, use a fresh account or run the reset SQL first): Snippet c. Customer sees "Your order continues at the full price". Monitor: amber **DISCOUNT VOIDED**. Say: "Rule engine: three coupons, the limit is one. Enforcement removed the discount and recalculated the total from the catalog."
2. **Price tampering** (`dave`): Snippet e. Monitor: red **BLOCKED**. Say: "Rule engine compares the price with the database: sent 100, catalog 3500, and the total does not match. The order never reaches payment." Read the sentence at the bottom of the monitor.
3. **COD spam** (`frank`): place the COD order: **HELD**, "2 of 2 previous COD orders were cancelled". Say: "Held for review, not blocked, because two bad orders is a warning." Then `gina`: Rs 17,500 COD from an unverified account: **HELD**.
   Then the anomaly part (if time): "Four accounts logged in on this one browser." (Pre-done in one window: `h4` places an order.) Monitor: step 2 all green, step 3 **HIGH RISK**, BLOCKED, "Account rate limited for 30 minutes". Say: "No rule was broken, but the behaviour is far from normal, so the Isolation Forest flags it. The account is rate limited."

**7:15 Wrap up (45 s).** Show the history table in the monitor and click an older row. "Every decision is stored in an insert-only audit log. If one component fails, the order is held, never accepted. Limits: the anomaly model is trained on synthetic data and the shop must never hold real data." Questions: see `docs/VIVA.md`.

## If something goes wrong on stage
- Checkout takes long right after switching ON: RuleLock was asleep. Say "free hosting wakes up; the shop waits up to 60 seconds and holds the order if RuleLock doesn't answer." That itself is the fail-safe.
- An order is HELD or BLOCKED that should pass: check that the customer window is the only one used by that account (a second account in the same browser triggers the anomaly block) and that the window is Incognito.
- Monitor shows a red "RuleLock is not reachable": open `https://<rulelock>/health` in a tab; wait 30 seconds and it clears by itself.
