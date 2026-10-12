"""c4 decision policy: turn the c2 result and the c3 score into one decision. Pure: no database, no side effects.

Reused from the team's deployed data-collection/decision.py (rule map, severity order, thresholds, tiers).
Changes: total_mismatch -> reject; thresholds are read from env when called; the hold action is `hold_cod_order`
for COD and `hold_order` for card; the result always has the same five keys; a missing or bad anomaly score
gives hold (never accept); it no longer calls the simulated actions (see actions.py for the real ones).

decide(...) -> {decision, reason, rule_code, action, account_action}
"""
import logging
import math
import os

logger = logging.getLogger(__name__)

# failed rule -> decision (same table as c2's RULE_ACTION)
RULE_ACTION_MAP = {
    "coupon_usage": "void_discount",
    "discount_range": "void_discount",
    "coupon_velocity": "void_discount",
    "minimum_purchase": "void_discount",
    "quantity_ceiling": "reject",
    "price_mismatch": "reject",
    "total_mismatch": "reject",
    "cod_order_value": "hold",
    "cod_abuse": "hold",
    "cod_abuse_severe": "reject",
}
SEVERITY = {"reject": 3, "hold": 2, "void_discount": 1}

# what c1 sends back to the shop for each decision (CONTRACT.md)
PAYMENT_ACTION = {"accept": "capture_payment", "void_discount": "void_discount",
                  "hold": "hold_payment", "reject": "block_payment"}
CUSTOMER_MESSAGE = {
    "accept": "Thank you! Your order is accepted.",
    "void_discount": "Your order continues at the full price",
    "hold": "Your order is being reviewed. We will contact you soon.",
    "reject": "Sorry, we could not process this order.",
}


def _float_env(name, default):
    try:
        value = float(os.environ.get(name, default))
        if math.isfinite(value):
            return value
    except (TypeError, ValueError):
        pass
    logger.warning("Invalid %s; using %s", name, default)
    return float(default)


def thresholds():
    """Read from env every call: hold -0.06, reject -0.1, rate limit 30 minutes."""
    minutes = int(_float_env("RATE_LIMIT_MINUTES", 30))
    return {"hold": _float_env("ANOMALY_HOLD_THRESHOLD", -0.06),
            "reject": _float_env("ANOMALY_REJECT_THRESHOLD", -0.1),
            "rate_limit_minutes": minutes if minutes > 0 else 30}


def payment_action_for(decision):
    return PAYMENT_ACTION.get(decision, "hold_payment")


def customer_message_for(decision):
    return CUSTOMER_MESSAGE.get(decision, CUSTOMER_MESSAGE["hold"])


def action_for(decision, payment_method):
    """The action name c4 reports for a decision."""
    if decision == "void_discount":
        return "void_discount"
    if decision == "reject":
        return "reject_order"
    if decision == "hold":
        return "hold_cod_order" if str(payment_method or "").upper() == "COD" else "hold_order"
    return "none"


def _finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _violation_code(violation):
    return violation.get("code") if isinstance(violation, dict) else None


def _severity_of(code):
    return SEVERITY[RULE_ACTION_MAP.get(code, "hold")]      # unknown code counts as hold


def decide(order_id, account_id, rule_passed, rule_reason, anomaly_score, payment_method, rule_code=None, violations=None):
    method = str(payment_method or "").upper()

    if not rule_passed:
        # the most severe action among ALL violations wins (reject > hold > void_discount; ties keep c2's order)
        chosen = None
        for v in violations or []:
            if _violation_code(v) is not None and (chosen is None or _severity_of(_violation_code(v)) > _severity_of(_violation_code(chosen))):
                chosen = v
        code = _violation_code(chosen) if chosen is not None else rule_code
        decision = RULE_ACTION_MAP.get(code, "hold")
        reason = rule_reason or (chosen.get("reason") if isinstance(chosen, dict) else None) or f"Rule check failed ({code})"
        return {"decision": decision, "reason": str(reason), "rule_code": code,
                "action": action_for(decision, method), "account_action": None}

    t = thresholds()
    score = _finite(anomaly_score)
    if score is None:
        return {"decision": "hold", "reason": "anomaly score unavailable; order held for review", "rule_code": None,
                "action": action_for("hold", method), "account_action": None}
    if score < t["reject"]:
        return {"decision": "reject", "reason": "anomaly score indicates elevated risk", "rule_code": None,
                "action": action_for("reject", method),
                "account_action": {"type": "rate_limit", "minutes": t["rate_limit_minutes"]}}
    if score < t["hold"]:
        return {"decision": "hold", "reason": "anomaly score requires review", "rule_code": None,
                "action": action_for("hold", method), "account_action": None}
    return {"decision": "accept", "reason": "passed all checks", "rule_code": None,
            "action": "none", "account_action": None}
