# c4-enforcement-engine (Mishen)

Decides what happens to an order and REALLY does it (through a database object that c1 passes in).

```python
import sys; sys.path.insert(0, "rulelock/c4-enforcement-engine")
from decision import decide, payment_action_for, customer_message_for
from actions import apply_enforcement
from audit import build_audit_payload, record

result = decide(order_id, account_id, rule_passed, rule_reason, anomaly_score, payment_method, rule_code, violations)
# -> {decision, reason, rule_code, action, account_action}      (pure, writes nothing)
done = apply_enforcement(result, order_id, account_id, db, payment_method)   # writes to the database
audit_row = build_audit_payload(done, order_id, account_id, payment_method, total, order_reference, anomaly_score)
```

## Policy (`decision.py`)
- **Rule failed:** the most severe action among ALL violations wins: reject > hold > void_discount (ties keep c2's order). `RULE_ACTION_MAP`: coupon_usage, discount_range, coupon_velocity, minimum_purchase -> void_discount; quantity_ceiling, price_mismatch, **total_mismatch**, cod_abuse_severe -> reject; cod_order_value, cod_abuse -> hold; unknown code -> hold.
- **Rules passed:** anomaly score below the reject threshold -> `reject` + `account_action = {"type": "rate_limit", "minutes": 30}`; below the hold threshold -> `hold`; otherwise `accept`. A missing, NaN or non-number score -> `hold` (never accept).
- `action` names: void_discount -> `void_discount`; reject -> `reject_order`; hold -> `hold_cod_order` for COD and `hold_order` for card (the decision name stays `hold`); accept -> `none`.
- `payment_action_for(decision)` and `customer_message_for(decision)` give c1 the contract's `payment_action` and the customer text (void_discount: "Your order continues at the full price").
- Env vars (read each call): `ANOMALY_HOLD_THRESHOLD` -0.06, `ANOMALY_REJECT_THRESHOLD` -0.1, `RATE_LIMIT_MINUTES` 30. Bad values fall back to the defaults.

## Actions (`actions.py`): what really changes
`db` is any object with:
| method | meaning |
|---|---|
| `update_order(order_id, fields: dict)` | PATCH the order row; raise on failure |
| `get_order_items(order_id)` | list of `{product_id, quantity, [unit_price], [sku]}` |
| `get_catalog()` | `{ "sku-<product id>": {name, price, sizes} }` (same shape c2 uses) |
| `insert_restriction(user_id, type, minutes, reason)` | row in `account_restrictions` with `until = now + minutes` |
| `insert_audit(payload)` | only used by `audit.record` |

| decision | effect on the order |
|---|---|
| accept | only `rulelock_decision` and `rulelock_reason` are stored; status unchanged |
| void_discount | `discount_value = 0`, `subtotal` and `total` recomputed from CATALOG prices x stored quantities, `coupons_applied = []`, status stays PENDING |
| hold | status HELD |
| reject | status BLOCKED; if `account_action` is set, a rate-limit row is inserted |
`rulelock_decision` and `rulelock_reason` are always stored. `apply_enforcement` returns the result plus `applied` (list of steps done) and `enforcement_error` (text or None).

**Failures:** if the order update or the void_discount recompute fails (database error, no catalog, unknown product, bad quantity, unknown decision) the result becomes `hold` with a reason, `account_action` is dropped, and c4 tries to mark the order HELD. It never turns into accept. One deliberate exception: if the order is already BLOCKED and only the rate-limit insert fails, the decision stays `reject` (stricter than hold) and `enforcement_error` explains it.

## Audit (`audit.py`)
`build_audit_payload(...)` returns only the columns of the team's `rulelock_audit_log` table (`data-collection/migrations/2026-10-03_rulelock_audit_log.sql`): event_id, event_type (`RULELOCK_REVIEW` or `RULELOCK_SIMULATION`), order_id, created_at, action (PASS / VOID / HOLD / REJECT), decision, reason, order_reference, account_id, payment_method, total, rule_code, anomaly_score. No names, phone, address or raw request. `record(db, payload)` is insert-only (no update or delete helper; the table also rejects them). **c1 owns the insert**: the team's RPC `record_rulelock_review(p_event jsonb, p_audit jsonb)` writes the transaction_events row and this audit row in one transaction.

## Changes from the team's deployed code
- `decide` is pure now: it no longer calls the simulated `void_discount / hold_cod_order / rate_limit_account` (those are real functions in `actions.py`, taking `db`).
- Added `total_mismatch -> reject`, thresholds read at call time, `hold_order` for card, a bad score holds, same 5 keys in every result, violations that are not dicts are ignored.
- The anomaly-reject path used to return the action `rate_limit_account`; now `action = reject_order` and the rate limit is in `account_action`.
- Removed the SQLite `audit_log.db`, `audit_log.py`, `/audit-log`, CORS with hard-coded origins from another project, Dockerfile. The old `enforcement-engine/` folder's tests (decisions `hold_cod_order`, `rate_limit_account`, `none`, `PREPAID`) were out of date and not used.

## Run
`pip install -r requirements.txt && pytest` (25 tests, fake db). Optional `python app.py` (port 5004): `POST /enforce` = decision only plus an audit preview, writes nothing; `GET /health`.
