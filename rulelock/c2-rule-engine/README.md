# c2-rule-engine (Sadini)

Business rules for one checkout. Pure Python, no database, no network.

```python
import sys; sys.path.insert(0, "rulelock/c2-rule-engine")
from rules import validate_transaction
result = validate_transaction(payload, catalog=None, coupon_review_count=None, coupon_percents=None)
```
Returns exactly `{passed, failures, violations[{code,reason}], checks[{code,label,passed,detail}], rule_code}` (CONTRACT.md). `rule_code` is the code of the most severe failure (reject > hold > void_discount; ties keep rule order).

## What c1 must pass in
- `payload`: the `/review-order` request, with the browser values untouched, **plus four keys c1 adds from its own data**: `account_verified` (bool: has a COMPLETED order), `past_orders` (int: earlier COD orders of this user), `past_refusals` (int: earlier COD orders that are REFUSED, or CANCELLED with cancelled_by = CUSTOMER), `used_coupons` (list of coupon codes this account already used; optional, missing = no reuse check). If they are missing: verified = true, counts = 0.
- `catalog`: `{ "sku-12": {"name": "...", "price": 3500, "sizes": null} }` (sku = `"sku-" + product id`). `None` = price and total checks are "Not applicable".
- `coupon_review_count`: reviews that had a coupon for this account in the last 24 h, **not counting this order**. `None` = velocity check "Not applicable".
- `coupon_percents` (optional): `{code: percent}` from the `coupons` table. Default CAKE50=50, CAKE20=20, CAKE10=10.

## Checks (all always appear in `checks`; "Not applicable: ..." counts as passed)
| code | fails when | usual action |
|---|---|---|
| coupon_usage | more than MAX_COUPONS coupons, an unknown code, or a coupon this account already used (`used_coupons`, added by c1 from `coupons_used`) | void_discount |
| discount_range | discount < 0, > subtotal, or > MAX_DISCOUNT_RATIO of subtotal | void_discount |
| quantity_ceiling | a line quantity is not a whole number from 1 to MAX_QUANTITY_PER_LINE, or there are no items | reject |
| minimum_purchase | a coupon is applied and subtotal < MIN_PURCHASE_AMOUNT | void_discount |
| price_mismatch | a unit price is more than PRICE_MATCH_TOLERANCE (1 %) from the catalog, missing, or the sku is unknown | reject |
| total_mismatch | submitted total differs from (catalog price x quantity, minus the summed coupon percents) by more than TOTAL_TOLERANCE | reject |
| coupon_velocity | `coupon_review_count` > COUPON_VELOCITY_MAX_REVIEWS and a coupon is applied | void_discount |
| cod_order_value | COD, account not verified, total > COD_UNVERIFIED_ORDER_CAP | hold |
| cod_abuse / cod_abuse_severe | COD, bad >= COD_BAD_HOLD (or COD_BAD_REJECT) and bad/total >= COD_BAD_RATIO | hold / reject |

`RULE_ACTION` in `rules.py` is this table as a dict. c4 makes the final decision.

Bad input (missing field, text, NaN, infinity, negative, wrong type) makes the matching check fail with a readable detail. A rule that raises is caught and shown as a failed check. Numeric strings like `"2"` are accepted as numbers.

## Env vars (defaults)
MAX_COUPONS 1, MAX_DISCOUNT_RATIO 0.6, MAX_QUANTITY_PER_LINE 20, MIN_PURCHASE_AMOUNT 500, COD_UNVERIFIED_ORDER_CAP 15000, COD_BAD_HOLD 2, COD_BAD_REJECT 3, COD_BAD_RATIO 0.5, COUPON_VELOCITY_MAX_REVIEWS 5, PRICE_MATCH_TOLERANCE 0.01, TOTAL_TOLERANCE 1.0. A bad value falls back to the default (with a log warning).

## Changes from the team's deployed `data-collection/rules.py`
- Removed `from db import ...`: catalog and review count are injected.
- Removed `MAX_COUPONS_PER_SESSION` (only `MAX_COUPONS`). `COD_BAD_RATIO` is now configurable (was a fixed 0.5).
- Added `total_mismatch`. `minimum_purchase` now only runs with a coupon.
- Fixed crashes: `float("abc")`, `int(nan)`, non-list items and non-dict payloads used to raise. A missing total is now a failure (it used to default to subtotal - discount); a missing `unit_price` is a failure (it used to be skipped).
- Unknown coupon codes fail `coupon_usage`. Empty `items` fails `quantity_ceiling`.
- COD checks are listed as "Not applicable" for card orders (before they were left out).
- Dropped: the old single-item `sku`/`quantity` payload form and the `account_id` lookup (c1 now supplies the count).
- The older `rule-engine/` folder (quantity 10, fixed discount range 0 to 5000, CORS) was not used.

## Run
`pip install -r requirements.txt && pytest` (24 tests). Standalone: `python app.py` (port 5002), `POST /validate` with the review JSON, optional extra keys `catalog` and `coupon_review_count`.
