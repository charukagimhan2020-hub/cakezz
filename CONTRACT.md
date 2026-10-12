# CONTRACT (single source of truth. No session may change it.)

## The contract (fixed; do not rename anything without telling me)
### Shop -> RuleLock
`POST {RULELOCK_URL}/review-order`, header `Authorization: Bearer <RULELOCK_API_TOKEN>`.
The order row is already inserted with status PENDING, so `order_id` is numeric and stable.
Request:
```json
{
  "order_id": 123, "order_reference": "CZ-20261010123456",
  "user_id": 7, "customer_name": "kamal",
  "session_id": "...", "device_id": "...", "phone_hash": "...", "address_hash": "...",
  "payment_method": "CARD" | "COD",
  "items": [{"sku": "sku-12", "quantity": 2, "unit_price": 3500}],
  "coupons_applied": ["CAKE20"],
  "subtotal": 7000, "discount_value": 1400, "total": 5600
}
```
IMPORTANT: `unit_price`, `quantity`, `subtotal`, `discount_value`, `total` are exactly what the browser submitted (untrusted). The shop must forward them as received. If the shop sent its own corrected numbers, RuleLock could never see tampering.

Response (always HTTP 200 when the review ran):
```json
{
  "order_id": 123, "order_reference": "CZ-...",
  "decision": "accept" | "void_discount" | "hold" | "reject",
  "reason": "text", "customer_message": "text",
  "payment_action": "capture_payment" | "void_discount" | "hold_payment" | "block_payment",
  "account_action": null | {"type": "rate_limit", "minutes": 30},
  "pipeline": {
    "c1_data_collection": {"status","events_in_session","session_features":{...},"account":{...}},
    "c2_rule_engine":     {"status":"pass"|"fail","checks":[{"code","label","passed","detail"}],"violations":[{"code","reason"}]},
    "c3_anomaly":         {"status":"normal"|"suspicious"|"high_risk","score","hold_threshold","reject_threshold"},
    "c4_enforcement":     {"decision","action","reason","account_action"}
  },
  "rulelock_enabled": true
}
```
Other RuleLock endpoints (all need the Bearer token except /health): `POST /events`, `GET /audit-log`, `GET /audit-log/<order_id_or_reference>`, `GET /dashboard/summary`, `GET /settings/rulelock`, `POST /settings/rulelock`, `GET /pipeline/info`, `GET /health`, `GET /ready`.

`POST /events` body: `{event_type: "LOGIN"|"BROWSE"|"ADD_TO_CART"|"APPLY_COUPON"|"CHECKOUT", user_id, session_id, device_id, phone_hash, address_hash, metadata:{}}`. The shop sends these only while the toggle is ON. They are what the anomaly features are built from.

### Between the four folders (Python function interfaces)
- c2: `validate_transaction(payload) -> {passed, failures[], violations[{code,reason}], checks[{code,label,passed,detail}], rule_code}`
- c3: `score_session(features: dict) -> (raw_score: float, is_anomaly: bool)` and `model_metadata()`. Feature names: `coupon_attempts_per_session`, `avg_seconds_between_requests`, `distinct_accounts_same_device`, `distinct_addresses_same_phone`.
- c4: `decide(order_id, account_id, rule_passed, rule_reason, anomaly_score, payment_method, rule_code, violations) -> {decision, reason, rule_code, action, account_action}` and `apply_enforcement(result, order_id, account_id)` which REALLY writes to Supabase: order status HELD/BLOCKED, discount voided (order total recalculated from the catalog), a row in `account_restrictions` for rate limits, and the audit row.
- c1: Flask app. Reads the order context, builds session features from `transaction_events`, calls c2, then c3, then c4, builds the `pipeline` object, stores the review (idempotent per order), returns the response.

### Rules to keep (from the team's code, all values configurable by env var)
MAX_COUPONS=1; MAX_DISCOUNT_RATIO=0.6; quantity must be 1 to 20 per line; unit price within 1% of the catalog; minimum purchase 500; unverified COD total over 15000 -> hold; account with 2+ bad COD orders (and 50%+ bad) -> hold, 3+ -> reject; more than 5 coupon reviews in 24 h -> void_discount; anomaly score below -0.06 -> hold, below -0.1 -> reject (and rate-limit account 30 minutes). "Bad COD order" = status REFUSED, or CANCELLED with cancelled_by = CUSTOMER. "Verified account" = at least one COMPLETED order.
New rule to add in c2: `total_mismatch` - the submitted total must equal the total recomputed from catalog prices, quantities and coupons (small tolerance) -> reject.
