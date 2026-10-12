Status: DONE
Part: 2
Last session: 2026-10-11

## Done (short)
c2 rule engine: `rules.py` (all old rules kept, new `total_mismatch`, `minimum_purchase` only with a coupon, safe on bad input, catalog and review count injected), `__init__.py`, tiny Flask `app.py`, 24 tests, README.

## Files created or changed
rulelock/c2-rule-engine/: rules.py, __init__.py, app.py, requirements.txt, README.md, tests/test_rules.py

## Interfaces (exact function signatures / endpoints / tables touched)
`validate_transaction(payload, catalog=None, coupon_review_count=None, coupon_percents=None) -> {passed, failures, violations, checks, rule_code}`
`RULE_ACTION` dict (code -> reject|hold|void_discount), `COUPON_PERCENTS`, individual `check_*` functions.
Standalone: `POST /validate` (JSON, optional keys catalog, coupon_review_count), `GET /health`. No tables touched.
Import: put `rulelock/c2-rule-engine` on sys.path, then `from rules import validate_transaction` (folder name has a hyphen, so it is not a normal package name).
Payload extras c1 must add: `account_verified`, `past_orders`, `past_refusals` (details in README).

## Env vars (name, meaning, default)
MAX_COUPONS 1, MAX_DISCOUNT_RATIO 0.6, MAX_QUANTITY_PER_LINE 20, MIN_PURCHASE_AMOUNT 500, COD_UNVERIFIED_ORDER_CAP 15000, COD_BAD_HOLD 2, COD_BAD_REJECT 3, COD_BAD_RATIO 0.5, COUPON_VELOCITY_MAX_REVIEWS 5, PRICE_MATCH_TOLERANCE 0.01, TOTAL_TOLERANCE 1.0

## How to run and test (and the test result you actually saw)
`cd rulelock/c2-rule-engine && pytest`. pytest is not installed in this sandbox, so I ran the same test functions with a small plain-Python runner: 24 passed, 0 failed. Also checked the Flask wrapper with Flask's test client (/health 200, /validate returns the result, bad body 400) and the package-style import.

## Kept / changed / why (reused teammate code)
Base = `data-collection/rules.py` (deployed). Kept every rule function, the env names and the severity order. Changes are listed in README.md ("Changes from the team's deployed rules.py"). The older `rule-engine/` folder was not used.

## Decisions (anything you chose because the brief was unclear)
- Env names are the team's deployed ones (MAX_QUANTITY_PER_LINE, MIN_PURCHASE_AMOUNT, COD_UNVERIFIED_ORDER_CAP, COD_BAD_HOLD, COD_BAD_REJECT, COUPON_VELOCITY_MAX_REVIEWS, PRICE_MATCH_TOLERANCE) plus new COD_BAD_RATIO and TOTAL_TOLERANCE. These differ from the names I put in `rulelock/.env.example` in Part 0.
- Numeric strings ("2") are accepted; text like "abc" fails the check.
- Missing `account_verified` = true, missing `past_orders`/`past_refusals` = 0 (as in the deployed code); c1 must always supply them.
- Unknown coupon code fails `coupon_usage`; empty items fail `quantity_ceiling` (reuses an existing code so c4 needs no new code).
- `total_mismatch` tolerance is an absolute 1.0 money unit.
- Tests do not use pytest fixtures, so they run with or without pytest.

## Known issues
- Real pytest not run here (plain runner used, same functions).
- If a rule raises an unexpected error it is shown as a failed check under that rule's own code.

## Requests to other parts
- Part 0 / Part 5 (`rulelock/.env.example`): replace the c2 variable names with the ones above (MAX_QUANTITY_PER_LINE, MIN_PURCHASE_AMOUNT, COD_UNVERIFIED_ORDER_CAP, COD_BAD_HOLD, COD_BAD_REJECT, COD_BAD_RATIO, COUPON_VELOCITY_MAX_REVIEWS, PRICE_MATCH_TOLERANCE, TOTAL_TOLERANCE) and drop MIN_QUANTITY, MAX_QUANTITY, MIN_PURCHASE, PRICE_TOLERANCE, COD_UNVERIFIED_HOLD_TOTAL, COD_BAD_HOLD_COUNT, COD_BAD_REJECT_COUNT, COUPON_REVIEWS_24H_LIMIT.
- Part 4 (c4): the rule-to-action map must include `total_mismatch` -> reject (full table is `RULE_ACTION` in c2 rules.py). The shop forwards `sku` as `"sku-" + product id`.
- Part 5 (c1): build the catalog as `{"sku-<id>": {"name", "price": base_price, "sizes"}}`; add `account_verified`, `past_orders`, `past_refusals` to the payload before calling c2; count coupon reviews for the last 24 h excluding the current order.
- Part 0: the team's three migration files are now available in `data-collection/migrations/` (they were not attached in the first session). They can replace the stand-in audit-log section of `supabase/schema.sql`.

## Next step (only if PARTIAL: exact file and function to continue from)
(not partial)
