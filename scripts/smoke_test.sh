#!/usr/bin/env bash
# Smoke test of the three demo attacks against a RUNNING RuleLock (local or Render).
#   BASE_URL=http://localhost:5001 RULELOCK_API_TOKEN=... ./scripts/smoke_test.sh
# Optional: SKU (default sku-1) and PRICE (default 3500) must match a product in your catalog.
# It uses "simulation": true, so it needs no real orders and changes no orders or accounts.
# Needs: bash, curl. Prints PASS/FAIL per check and exits 1 if any check fails.
set -u
BASE_URL="${BASE_URL:-http://localhost:5001}"
TOKEN="${RULELOCK_API_TOKEN:-}"
SKU="${SKU:-sku-1}"
PRICE="${PRICE:-3500}"
RUN="$(date +%s)"
FAILED=0
AUTH=(-H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json")

post() { curl -sS --max-time 90 -X POST "${AUTH[@]}" "$BASE_URL$1" -d "$2"; }
decision_of() { grep -o '"decision":"[a-z_]*"' | head -1 | cut -d'"' -f4; }
check() {   # name, expected decision, response
  local got; got="$(printf '%s' "$3" | decision_of)"
  if [ "$got" = "$2" ]; then echo "PASS  $1 -> $got"; else echo "FAIL  $1 -> expected $2, got '${got:-no answer}'"; echo "      $3" | cut -c1-300; FAILED=1; fi
}

echo "RuleLock at $BASE_URL (sku $SKU, price $PRICE)"
curl -sS --max-time 90 "$BASE_URL/health" | grep -q '"status":"ok"' && echo "PASS  /health" || { echo "FAIL  /health (is the service running?)"; exit 1; }
curl -sS --max-time 90 "$BASE_URL/ready" | grep -q '"ready":true' && echo "PASS  /ready" || { echo "FAIL  /ready (model or Supabase not ready)"; FAILED=1; }

TOTAL=$((PRICE * 2))
ITEM="{\"sku\":\"$SKU\",\"quantity\":2,\"unit_price\":$PRICE}"
BASE="\"user_id\":7,\"customer_name\":\"smoke\",\"session_id\":\"smoke-$RUN\",\"device_id\":\"smoke-dev-$RUN\",\"payment_method\":\"CARD\",\"simulation\":true"

echo "--- control: clean order"
check "clean order" accept "$(post /review-order "{\"order_id\":$((900000 + RUN % 90000)),$BASE,\"items\":[$ITEM],\"coupons_applied\":[],\"subtotal\":$TOTAL,\"discount_value\":0,\"total\":$TOTAL}")"

echo "--- attack 1: coupon stacking (3 coupons, 80% off)"
DISC=$((TOTAL * 80 / 100)); LEFT=$((TOTAL - DISC))
check "coupon stacking" void_discount "$(post /review-order "{\"order_id\":$((910000 + RUN % 90000)),$BASE,\"items\":[$ITEM],\"coupons_applied\":[\"CAKE50\",\"CAKE20\",\"CAKE10\"],\"subtotal\":$TOTAL,\"discount_value\":$DISC,\"total\":$LEFT}")"

echo "--- attack 1b: reusing a coupon the account already used (simulated account that used CAKE10)"
D10=$((TOTAL / 10)); L10=$((TOTAL - D10))
check "coupon reuse" void_discount "$(post /review-order "{\"order_id\":$((970000 + RUN % 90000)),\"user_id\":7,\"customer_name\":\"smoke\",\"session_id\":\"smoke-$RUN\",\"payment_method\":\"CARD\",\"simulation\":true,\"simulated_account\":{\"used_coupons\":[\"CAKE10\"],\"completed_orders\":1},\"items\":[$ITEM],\"coupons_applied\":[\"CAKE10\"],\"subtotal\":$TOTAL,\"discount_value\":$D10,\"total\":$L10}")"

echo "--- attack 2: price and quantity tampering (unit price 100, quantity 9999, total edited)"
check "price tampering" reject "$(post /review-order "{\"order_id\":$((920000 + RUN % 90000)),$BASE,\"items\":[{\"sku\":\"$SKU\",\"quantity\":2,\"unit_price\":100}],\"coupons_applied\":[],\"subtotal\":200,\"discount_value\":0,\"total\":200}")"
check "quantity 9999" reject "$(post /review-order "{\"order_id\":$((930000 + RUN % 90000)),$BASE,\"items\":[{\"sku\":\"$SKU\",\"quantity\":9999,\"unit_price\":$PRICE}],\"coupons_applied\":[],\"subtotal\":$((PRICE * 9999)),\"discount_value\":0,\"total\":$((PRICE * 9999))}")"
check "tampered total only" reject "$(post /review-order "{\"order_id\":$((940000 + RUN % 90000)),$BASE,\"items\":[$ITEM],\"coupons_applied\":[],\"subtotal\":$TOTAL,\"discount_value\":0,\"total\":1}")"

echo "--- attack 3: COD abuse (account with 4 earlier COD orders, 3 cancelled by the customer)"
check "COD abuse" reject "$(post /review-order "{\"order_id\":$((950000 + RUN % 90000)),\"user_id\":7,\"customer_name\":\"smoke\",\"session_id\":\"smoke-$RUN\",\"payment_method\":\"COD\",\"simulation\":true,\"simulated_account\":{\"cod_orders\":4,\"cod_bad\":3,\"completed_orders\":1},\"items\":[$ITEM],\"coupons_applied\":[],\"subtotal\":$TOTAL,\"discount_value\":0,\"total\":$TOTAL}")"

echo "--- attack 4 (anomaly): 9 coupon attempts a second apart, then a clean order from the same session"
for i in 1 2 3 4 5 6 7 8 9; do
  post /events "{\"event_type\":\"APPLY_COUPON\",\"user_id\":7,\"session_id\":\"burst-$RUN\",\"device_id\":\"smoke-dev-$RUN\"}" > /dev/null; sleep 1
done
R="$(post /review-order "{\"order_id\":$((960000 + RUN % 90000)),\"user_id\":7,\"customer_name\":\"smoke\",\"session_id\":\"burst-$RUN\",\"payment_method\":\"CARD\",\"simulation\":true,\"items\":[$ITEM],\"coupons_applied\":[],\"subtotal\":$TOTAL,\"discount_value\":0,\"total\":$TOTAL}")"
GOT="$(printf '%s' "$R" | decision_of)"
if [ "$GOT" = "hold" ] || [ "$GOT" = "reject" ]; then echo "PASS  coupon burst -> $GOT"; else echo "FAIL  coupon burst -> expected hold or reject, got '${GOT:-no answer}'"; FAILED=1; fi

echo "--- the monitor can read the newest live review"
curl -sS --max-time 90 "${AUTH[@]}" "$BASE_URL/audit-log/latest" | grep -q 'c4_enforcement' && echo "PASS  /audit-log/latest has a pipeline" || echo "NOTE  /audit-log/latest has no live review yet (simulations are not listed; place a real order in the shop)"

[ "$FAILED" = "0" ] && echo "ALL CHECKS PASSED" || { echo "SOME CHECKS FAILED"; exit 1; }
