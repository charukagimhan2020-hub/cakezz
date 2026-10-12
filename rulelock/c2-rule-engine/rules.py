"""c2 rule engine: business rules for one checkout.

Reused from the team's deployed `data-collection/rules.py` (rule functions, env names, severity order),
with these changes (details in README.md):
  * no database import: the catalog and the coupon review count are INJECTED by c1;
  * new rule `total_mismatch`; `minimum_purchase` only applies when a coupon is applied;
  * bad input (missing field, text instead of a number, NaN, negative) gives a failed check, never a crash;
  * every check, passed or failed, is returned with a readable `detail`.

Entry point: validate_transaction(payload, catalog=None, coupon_review_count=None, coupon_percents=None)
Returns exactly: {passed, failures, violations, checks, rule_code}  (see CONTRACT.md).
"""
from dataclasses import dataclass
import logging
import math
import os

logger = logging.getLogger(__name__)


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        logger.warning("Invalid integer rule setting %s; using default", name)
        return int(default)


def _float_env(name, default):
    try:
        value = float(os.environ.get(name, default))
        if math.isfinite(value):
            return value
    except (TypeError, ValueError):
        pass
    logger.warning("Invalid numeric rule setting %s; using default", name)
    return float(default)


# ---- settings (all can be changed by env var) ----
MAX_COUPONS = _int_env("MAX_COUPONS", 1)
MAX_DISCOUNT_RATIO = _float_env("MAX_DISCOUNT_RATIO", 0.6)
MAX_QUANTITY_PER_LINE = _int_env("MAX_QUANTITY_PER_LINE", 20)       # quantity must be 1..this
MIN_PURCHASE_AMOUNT = _float_env("MIN_PURCHASE_AMOUNT", 500)        # only checked when a coupon is applied
COD_UNVERIFIED_ORDER_CAP = _float_env("COD_UNVERIFIED_ORDER_CAP", 15000)
COD_BAD_HOLD = _int_env("COD_BAD_HOLD", 2)
COD_BAD_REJECT = _int_env("COD_BAD_REJECT", 3)
COD_BAD_RATIO = _float_env("COD_BAD_RATIO", 0.5)
COUPON_VELOCITY_MAX_REVIEWS = _int_env("COUPON_VELOCITY_MAX_REVIEWS", 5)
PRICE_MATCH_TOLERANCE = _float_env("PRICE_MATCH_TOLERANCE", 0.01)   # 1 % per unit price
TOTAL_TOLERANCE = _float_env("TOTAL_TOLERANCE", 1.0)                # money units, for the recomputed total

# coupon code -> percent. c1 may pass the real table from the database instead.
COUPON_PERCENTS = {"CAKE50": 50, "CAKE20": 20, "CAKE10": 10}

# what each failed rule means for the order (c4 decides the final action; this is for ordering and docs)
RULE_ACTION = {
    "quantity_ceiling": "reject", "price_mismatch": "reject", "total_mismatch": "reject",
    "cod_abuse_severe": "reject",
    "cod_order_value": "hold", "cod_abuse": "hold",
    "coupon_usage": "void_discount", "discount_range": "void_discount",
    "coupon_velocity": "void_discount", "minimum_purchase": "void_discount",
}
_SEVERITY = {"reject": 3, "hold": 2, "void_discount": 1}

LABELS = {
    "coupon_usage": "Coupon usage", "discount_range": "Discount range", "quantity_ceiling": "Quantity limit",
    "minimum_purchase": "Minimum purchase", "price_mismatch": "Prices match catalog",
    "total_mismatch": "Total matches catalog", "coupon_velocity": "Coupon velocity",
    "cod_order_value": "COD order value", "cod_abuse": "COD abuse history", "cod_abuse_severe": "COD abuse history",
}


@dataclass
class RuleResult:
    passed: bool
    reason: str = ""
    code: str = ""


# ---------- safe input helpers ----------
def _num(value):
    """A finite float, or None (missing, text that is not a number, NaN, infinity, bool)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _show(value):
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _truthy(value, default=True):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "none")
    return bool(value)


def _na(code, why):
    return RuleResult(True, f"Not applicable: {why}", code)


# ---------- the rules ----------
def check_coupon_usage(coupons_applied, coupon_percents=None, used_coupons=None):
    """Stacking (more than MAX_COUPONS), unknown codes, and a coupon this account already used (used_coupons, from c1)."""
    percents = COUPON_PERCENTS if coupon_percents is None else coupon_percents
    if coupons_applied is None:
        coupons_applied = []
    if not isinstance(coupons_applied, (list, tuple)):
        return RuleResult(False, f"coupons_applied must be a list, got {_show(coupons_applied)}", "coupon_usage")
    codes = [str(c).strip().upper() for c in coupons_applied]
    if len(codes) > MAX_COUPONS:
        return RuleResult(False, f"Coupons {' + '.join(codes)} stacked ({len(codes)} applied, max {MAX_COUPONS})", "coupon_usage")
    unknown = [c for c in codes if c not in percents]
    if unknown:
        return RuleResult(False, f"Unknown coupon code(s): {', '.join(unknown)}", "coupon_usage")
    if isinstance(used_coupons, (list, tuple, set)):
        used = {str(c).strip().upper() for c in used_coupons}
        reused = [c for c in codes if c in used]
        if reused:
            return RuleResult(False, f"Coupon {', '.join(reused)} was already used by this account", "coupon_usage")
    return RuleResult(True, f"{len(codes)} coupon(s) applied (max {MAX_COUPONS})", "coupon_usage")


def check_discount_range(discount_value, subtotal):
    d, s = _num(discount_value), _num(subtotal)
    if d is None or s is None:
        return RuleResult(False, f"Discount {_show(discount_value)} or subtotal {_show(subtotal)} is missing or not a valid number", "discount_range")
    if s < 0 or d < 0 or d > s or d > s * MAX_DISCOUNT_RATIO:
        return RuleResult(False, f"Discount {d:g} is not within {MAX_DISCOUNT_RATIO:.0%} of subtotal {s:g}", "discount_range")
    return RuleResult(True, f"Discount {d:g} is within {MAX_DISCOUNT_RATIO:.0%} of subtotal {s:g}", "discount_range")


def check_quantity_ceiling(sku, quantity):
    q = _num(quantity)
    if q is None:
        return RuleResult(False, f"Quantity {_show(quantity)} for {sku} is missing or not a valid number", "quantity_ceiling")
    if q != math.floor(q):
        return RuleResult(False, f"Quantity {q:g} for {sku} is not a whole number", "quantity_ceiling")
    if q < 1 or q > MAX_QUANTITY_PER_LINE:
        return RuleResult(False, f"Quantity {q:g} for {sku} is outside the allowed range 1 to {MAX_QUANTITY_PER_LINE}", "quantity_ceiling")
    return RuleResult(True, f"Quantity {q:g} for {sku} is within 1 to {MAX_QUANTITY_PER_LINE}", "quantity_ceiling")


def check_minimum_purchase(subtotal, coupons_applied):
    """Only meaningful when a discount could be voided, so it only runs when a coupon is applied."""
    if not coupons_applied:
        return _na("minimum_purchase", "no coupon applied")
    s = _num(subtotal)
    if s is None:
        return RuleResult(False, f"Subtotal {_show(subtotal)} is missing or not a valid number", "minimum_purchase")
    if s < MIN_PURCHASE_AMOUNT:
        return RuleResult(False, f"Subtotal {s:g} is below the minimum purchase of {MIN_PURCHASE_AMOUNT:g} for a coupon", "minimum_purchase")
    return RuleResult(True, f"Subtotal {s:g} meets the minimum purchase of {MIN_PURCHASE_AMOUNT:g}", "minimum_purchase")


def _catalog_price(product, size):
    """Catalog unit price for a product and an optional size (same logic as the deployed code)."""
    sizes = product.get("sizes")
    if isinstance(sizes, dict) and size in sizes:
        value = sizes[size]
        return float(value.get("price")) if isinstance(value, dict) and value.get("price") is not None else float(value)
    if isinstance(sizes, list):
        for entry in sizes:
            if isinstance(entry, dict) and str(entry.get("size")) == str(size):
                value = entry.get("price", entry.get("unit_price"))
                if value is not None:
                    return float(value)
    base = float(product["price"])
    try:
        kg = float(str(size).lower().replace("kg", "").strip())
    except (TypeError, ValueError):
        kg = 1.0
    return base * kg


def _expected_price(catalog, item):
    """(expected_price, error_text). error_text is None when the price could be found."""
    sku = str(item.get("sku", ""))
    product = catalog.get(sku) if isinstance(catalog, dict) else None
    if not isinstance(product, dict):
        return None, f"{sku or '(no sku)'}: not in the catalog"
    try:
        expected = _catalog_price(product, item.get("size"))
    except (KeyError, TypeError, ValueError):
        return None, f"{sku}: catalog price could not be read"
    if not math.isfinite(expected) or expected <= 0:
        return None, f"{sku}: catalog price {expected:g} is not usable"
    return expected, None


def check_price_mismatch(items, catalog=None):
    if catalog is None:
        return _na("price_mismatch", "no catalog supplied")
    if not items:
        return _na("price_mismatch", "no items to compare")
    bad, good = [], []
    for item in items:
        sku = str(item.get("sku", ""))
        expected, err = _expected_price(catalog, item)
        if err:
            bad.append(err)
            continue
        supplied = _num(item.get("unit_price"))
        if supplied is None:
            bad.append(f"{sku}: unit_price {_show(item.get('unit_price'))} is missing or not a valid number")
        elif abs(supplied - expected) / expected > PRICE_MATCH_TOLERANCE:
            bad.append(f"{sku}: supplied {supplied:g}, catalog {expected:g}")
        else:
            good.append(f"{sku}: supplied {supplied:g}, catalog {expected:g}")
    if bad:
        return RuleResult(False, "Price mismatch: " + "; ".join(bad), "price_mismatch")
    return RuleResult(True, "; ".join(good), "price_mismatch")


def check_total_mismatch(items, coupons_applied, submitted_total, catalog=None, coupon_percents=None):
    """Recompute the total from catalog prices, quantities and coupon percentages (stacked coupons add up)."""
    if catalog is None:
        return _na("total_mismatch", "no catalog supplied")
    percents = COUPON_PERCENTS if coupon_percents is None else coupon_percents
    subtotal = 0.0
    for item in items:
        expected, err = _expected_price(catalog, item)
        qty = _num(item.get("quantity"))
        if err or qty is None:
            why = err or f"{item.get('sku', '(no sku)')}: quantity {_show(item.get('quantity'))} is not a valid number"
            return RuleResult(False, f"Total could not be recomputed ({why})", "total_mismatch")
        subtotal += expected * qty
    codes = [str(c).strip().upper() for c in coupons_applied] if isinstance(coupons_applied, (list, tuple)) else []
    pct = sum(float(percents.get(c, 0)) for c in codes)
    expected_total = round(subtotal * (1 - pct / 100.0), 2)
    total = _num(submitted_total)
    if total is None:
        return RuleResult(False, f"Submitted total {_show(submitted_total)} is missing or not a valid number (expected {expected_total:g})", "total_mismatch")
    diff = abs(total - expected_total)
    if diff > TOTAL_TOLERANCE:
        return RuleResult(False, f"Submitted total {total:g} does not match the total {expected_total:g} recomputed from catalog prices, quantities and coupons (difference {diff:g})", "total_mismatch")
    return RuleResult(True, f"Submitted total {total:g} matches the recomputed total {expected_total:g}", "total_mismatch")


def check_coupon_velocity(coupons_applied, review_count):
    """review_count = reviews with a coupon for this account in the last 24 h (given by c1)."""
    if review_count is None:
        return _na("coupon_velocity", "no review history supplied")
    if not coupons_applied:
        return _na("coupon_velocity", "no coupon applied")
    count = _num(review_count)
    if count is None or count < 0:
        return RuleResult(False, f"Coupon review count {_show(review_count)} is not a valid number", "coupon_velocity")
    if count > COUPON_VELOCITY_MAX_REVIEWS:
        return RuleResult(False, f"Coupon velocity {count:g} reviews in 24 h exceeds the limit of {COUPON_VELOCITY_MAX_REVIEWS}", "coupon_velocity")
    return RuleResult(True, f"Coupon velocity {count:g} reviews in 24 h (max {COUPON_VELOCITY_MAX_REVIEWS})", "coupon_velocity")


def check_cod_order_value(total, account_verified):
    t = _num(total)
    if t is None:
        return RuleResult(False, f"COD total {_show(total)} is missing or not a valid number", "cod_order_value")
    if not account_verified and t > COD_UNVERIFIED_ORDER_CAP:
        return RuleResult(False, f"Unverified COD total {t:g} exceeds the cap of {COD_UNVERIFIED_ORDER_CAP:g}", "cod_order_value")
    return RuleResult(True, f"COD total {t:g}; verified={bool(account_verified)}; cap for unverified {COD_UNVERIFIED_ORDER_CAP:g}", "cod_order_value")


def check_cod_abuse(total, bad):
    """total = this account's earlier COD orders; bad = REFUSED or CANCELLED by the customer."""
    n, b = _num(total), _num(bad)
    if n is None or b is None or n < 0 or b < 0:
        return RuleResult(False, f"COD history ({_show(total)} orders, {_show(bad)} bad) is not valid", "cod_abuse")
    n, b = int(n), int(b)
    n = max(n, b)
    rate = b / n if n else 0.0
    detail = f"COD abuse: {b} of {n} previous COD orders were cancelled by the customer or refused"
    if b >= COD_BAD_REJECT and rate >= COD_BAD_RATIO:
        return RuleResult(False, detail, "cod_abuse_severe")
    if b >= COD_BAD_HOLD and rate >= COD_BAD_RATIO:
        return RuleResult(False, detail, "cod_abuse")
    return RuleResult(True, detail, "cod_abuse")


def _safe(code, fn, *args):
    try:
        return fn(*args)
    except Exception as exc:   # a rule must never crash the review
        logger.exception("Rule %s failed to run", code)
        return RuleResult(False, f"Check could not run ({exc.__class__.__name__})", code)


# ---------- the whole validation ----------
def validate_transaction(payload, catalog=None, coupon_review_count=None, coupon_percents=None):
    """payload: the review-order request (CONTRACT.md) plus, added by c1 from its own data:
         account_verified (bool), past_orders (int, earlier COD orders), past_refusals (int, bad COD orders),
         used_coupons (list of coupon codes this account already used; optional).
       catalog: {sku: {name, price, sizes}} or None (price and total checks are then 'not applicable').
       coupon_review_count: int or None (velocity check is then 'not applicable')."""
    t = payload if isinstance(payload, dict) else {}
    raw_items = t.get("items")
    items = []
    if isinstance(raw_items, list):
        for it in raw_items:
            if isinstance(it, dict):
                items.append({**it, "quantity": it.get("quantity", it.get("qty"))})
            else:
                items.append({"sku": "(bad item)", "quantity": None})
    coupons = t.get("coupons_applied")
    coupons = [] if coupons is None else coupons
    discount = t.get("discount_value", 0) if t.get("discount_value") is not None else 0
    subtotal = t.get("subtotal")
    total = t.get("total")
    method = str(t.get("payment_method", "CARD")).upper()

    results = [_safe("coupon_usage", check_coupon_usage, coupons, coupon_percents, t.get("used_coupons")),
               _safe("discount_range", check_discount_range, discount, subtotal)]
    if items:
        for it in items:
            results.append(_safe("quantity_ceiling", check_quantity_ceiling, str(it.get("sku", "(no sku)")), it.get("quantity")))
    else:
        results.append(RuleResult(False, "The order has no items", "quantity_ceiling"))
    results.append(_safe("minimum_purchase", check_minimum_purchase, subtotal, coupons))
    results.append(_safe("price_mismatch", check_price_mismatch, items, catalog))
    results.append(_safe("total_mismatch", check_total_mismatch, items, coupons, total, catalog, coupon_percents))
    results.append(_safe("coupon_velocity", check_coupon_velocity, coupons, coupon_review_count))
    if method == "COD":
        results.append(_safe("cod_order_value", check_cod_order_value, total, _truthy(t.get("account_verified"), True)))
        past = t.get("past_orders", 0) if t.get("past_orders") is not None else 0
        bad = t.get("past_refusals", 0) if t.get("past_refusals") is not None else 0
        results.append(_safe("cod_abuse", check_cod_abuse, past, bad))
    else:
        results.append(_na("cod_order_value", f"payment method is {method}, not COD"))
        results.append(_na("cod_abuse", f"payment method is {method}, not COD"))

    failed = sorted((r for r in results if not r.passed),
                    key=lambda r: _SEVERITY[RULE_ACTION.get(r.code, "hold")], reverse=True)   # stable: ties keep rule order
    violations = [{"code": r.code, "reason": r.reason} for r in failed]
    checks = [{"code": r.code, "label": LABELS.get(r.code, r.code.replace("_", " ").title()),
               "passed": r.passed, "detail": r.reason} for r in results]
    return {"passed": not violations, "failures": [v["reason"] for v in violations],
            "violations": violations, "checks": checks,
            "rule_code": violations[0]["code"] if violations else None}
