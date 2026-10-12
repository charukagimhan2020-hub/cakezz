Status: DONE
Part: 4
Last session: 2026-10-11

## Done (short)
c4: `decision.py` (pure policy), `actions.py` (real order changes through an injected `db`), `audit.py` (minimal insert-only payload), `__init__.py`, decision-only `app.py`, 25 tests with a fake db, README.

## Files created or changed
rulelock/c4-enforcement-engine/: decision.py, actions.py, audit.py, __init__.py, app.py, requirements.txt, README.md, tests/test_c4.py

## Interfaces (exact function signatures / endpoints / tables touched)
`decide(order_id, account_id, rule_passed, rule_reason, anomaly_score, payment_method, rule_code=None, violations=None) -> {decision, reason, rule_code, action, account_action}`
`apply_enforcement(result, order_id, account_id, db, payment_method=None) -> result + {applied: [...], enforcement_error: str|None}`
`decision.thresholds()`, `payment_action_for(decision)`, `customer_message_for(decision)`, `RULE_ACTION_MAP`
`audit.build_audit_payload(result, order_id, account_id=None, payment_method=None, total=None, order_reference=None, anomaly_score=None, event_type="RULELOCK_REVIEW", event_id=None, created_at=None) -> dict`, `audit.record(db, payload)`
Injected `db` interface (c1 implements): `update_order(order_id, fields)`, `get_order_items(order_id) -> [{product_id, quantity, ...}]`, `get_catalog() -> {"sku-<id>": {name, price, sizes}}`, `insert_restriction(user_id, type, minutes, reason)`, `insert_audit(payload)`.
Tables written (through db): orders (status, discount_value, subtotal, total, coupons_applied, rulelock_decision, rulelock_reason), account_restrictions, rulelock_audit_log.
Standalone: `POST /enforce` (decision only, writes nothing), `GET /health`.
Import: put `rulelock/c4-enforcement-engine` on sys.path, then `from decision import decide`, `from actions import apply_enforcement`, `from audit import ...`.

## Env vars (name, meaning, default)
ANOMALY_HOLD_THRESHOLD -0.06, ANOMALY_REJECT_THRESHOLD -0.1, RATE_LIMIT_MINUTES 30 (read at call time)

## How to run and test (and the test result you actually saw)
`cd rulelock/c4-enforcement-engine && pytest`. pytest is not installed in this sandbox, so the same test functions ran with a plain-Python runner: 25 passed, 0 failed. No real database was used (fake db only). The c2/c4 rule-map agreement is tested by reading `../c2-rule-engine/rules.py`.

## Kept / changed / why (reused teammate code)
Base = deployed `data-collection/decision.py` and `actions.py`. Kept: decide() rule, RULE_ACTION_MAP, severity order, thresholds, anomaly tiers. Changed (details in README): decide is pure, actions are real and take `db`, total_mismatch added, `hold_order` for card, bad score holds, SQLite audit and CORS removed. The old `enforcement-engine/` folder was not used.

## Decisions (anything you chose because the brief was unclear)
- Audit payload follows the TEAM's migration columns (event_id, event_type, action PASS/VOID/HOLD/REJECT, ...), not the stand-in `rulelock_audit_log` I wrote in Part 0.
- void_discount also sets `subtotal` = recomputed total and `coupons_applied = []`, and explicitly sets status PENDING.
- If only the rate-limit insert fails after the order was BLOCKED, the decision stays reject (stricter than hold) and `enforcement_error` is set. Any failure before/while changing the order becomes hold.
- Rule-fail result `reason` = c2's `rule_reason` if given, else the most severe violation's reason.
- Anomaly rate limit rows use the `reason` of the decision; account id must be a numeric user id.
- Optional `payment_method` argument added to `apply_enforcement` (to pick hold_cod_order vs hold_order when the result lacks it).

## Known issues
- Real pytest not run (plain runner, same functions). Never run against Supabase.
- c1 must implement the `db` object; shop reloads the order after review (shop already does this).

## Requests to other parts
- Part 0: replace the stand-in audit section of `supabase/schema.sql` with the team's three migrations (`data-collection/migrations/`): table `rulelock_audit_log` (audit_id, event_id, event_type, ..., action, decision, reason, order_reference, account_id, payment_method, total, rule_code, anomaly_score), RPC `record_rulelock_review(p_event jsonb, p_audit jsonb)` and the one-review-per-order unique indexes. My stand-in RPC has a different signature and no `account_id`/`action` columns.
- Part 5 (c1): implement the `db` object (Supabase REST) with the five methods above; `get_order_items` must return rows from `order_items` (product_id, quantity); build `payment_action`/`customer_message` with `decision.payment_action_for/customer_message_for`; build the audit row with `audit.build_audit_payload(...)` and store it with the team's RPC (both transaction_events and audit in one call); pass `anomaly_score=None` to decide() when c3 fails (it then holds).
- Part 5 (c1): after c4, the shop already reloads the order; c4 recomputes subtotal/discount/total itself.

## Next step (only if PARTIAL: exact file and function to continue from)
(not partial)
