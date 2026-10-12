"""c4 actions: REALLY change the order in the database, through an injected `db` object.

c4 never imports c1. c1 passes its Supabase helper as `db`, an object with these methods:
    db.update_order(order_id, fields: dict)                     -> None   (raise on failure)
    db.get_order_items(order_id)                                -> list of {product_id, quantity, [unit_price], [sku]}
    db.get_catalog()                                            -> {sku: {name, price, sizes}}   ("sku-<product id>")
    db.insert_restriction(user_id, type, minutes, reason)       -> None   (account_restrictions row until now + minutes)
    db.insert_audit(payload: dict)                              -> None   (only used by audit.record)

apply_enforcement(result, order_id, account_id, db, payment_method=None) -> result dict + {applied, enforcement_error}
If a step fails the result becomes `hold` with a reason. It never turns into accept.
"""
import math

try:
    from .decision import action_for
except ImportError:                       # folder is on sys.path
    from decision import action_for


class EnforcementError(Exception):
    pass


def _short(text, limit=500):
    return str(text)[:limit]


def _sku(item):
    sku = item.get("sku")
    return str(sku) if sku else f"sku-{item.get('product_id')}"


def recompute_total(items, catalog):
    """Order total from CATALOG prices and the stored quantities (no discount). Raises EnforcementError."""
    if not items:
        raise EnforcementError("order has no items to recompute")
    if not isinstance(catalog, dict):
        raise EnforcementError("catalog is not available")
    total = 0.0
    for item in items:
        sku = _sku(item)
        product = catalog.get(sku)
        if not isinstance(product, dict):
            raise EnforcementError(f"{sku} is not in the catalog")
        try:
            price, qty = float(product["price"]), float(item["quantity"])
        except (KeyError, TypeError, ValueError):
            raise EnforcementError(f"{sku} has no usable price or quantity")
        if not (math.isfinite(price) and math.isfinite(qty)) or price < 0:
            raise EnforcementError(f"{sku} has no usable price or quantity")
        total += price * qty
    return round(total, 2)


def _user_id(account_id):
    if isinstance(account_id, bool) or account_id is None:
        raise EnforcementError("no account id for the rate limit")
    if isinstance(account_id, int):
        return account_id
    text = str(account_id).strip()
    if text.isdigit():
        return int(text)
    raise EnforcementError(f"account id {text!r} is not a user id")


def record_decision(order_id, db, decision, reason):
    """accept: nothing changes except the stored decision and reason."""
    db.update_order(order_id, {"rulelock_decision": decision, "rulelock_reason": _short(reason)})
    return {"action": "none", "order_id": order_id, "status": "recorded"}


def void_discount(order_id, db, reason=""):
    """discount_value = 0, total recomputed from the catalog, order stays PENDING so it can continue."""
    total = recompute_total(db.get_order_items(order_id), db.get_catalog())
    db.update_order(order_id, {"status": "PENDING", "subtotal": total, "discount_value": 0, "total": total,
                               "coupons_applied": [], "rulelock_decision": "void_discount",
                               "rulelock_reason": _short(reason)})
    return {"action": "void_discount", "order_id": order_id, "status": "executed", "total": total}


def hold_cod_order(order_id, db, reason=""):
    db.update_order(order_id, {"status": "HELD", "rulelock_decision": "hold", "rulelock_reason": _short(reason)})
    return {"action": "hold_cod_order", "order_id": order_id, "status": "held"}


def hold_order(order_id, db, reason=""):
    db.update_order(order_id, {"status": "HELD", "rulelock_decision": "hold", "rulelock_reason": _short(reason)})
    return {"action": "hold_order", "order_id": order_id, "status": "held"}


def reject_order(order_id, db, reason=""):
    db.update_order(order_id, {"status": "BLOCKED", "rulelock_decision": "reject", "rulelock_reason": _short(reason)})
    return {"action": "reject_order", "order_id": order_id, "status": "blocked"}


def rate_limit_account(account_id, db, minutes=30, reason=""):
    user_id = _user_id(account_id)
    db.insert_restriction(user_id, "rate_limit", int(minutes), _short(reason, 300))
    return {"action": "rate_limit_account", "account_id": user_id, "status": "rate_limited", "minutes": int(minutes)}


def _held_after_failure(result, order_id, db, payment_method, error):
    reason = _short(f"Enforcement failed ({error}); order held for safety. Planned decision: "
                    f"{result.get('decision')} - {result.get('reason')}", 500)
    try:                                   # best effort: mark the order HELD; the caller also holds it
        db.update_order(order_id, {"status": "HELD", "rulelock_decision": "hold", "rulelock_reason": reason})
    except Exception:
        pass
    out = dict(result)
    out.update({"decision": "hold", "reason": reason, "account_action": None, "applied": [],
                "action": action_for("hold", payment_method), "enforcement_error": _short(error, 200)})
    return out


def apply_enforcement(result, order_id, account_id, db, payment_method=None):
    result = dict(result or {})
    decision, reason = result.get("decision"), str(result.get("reason") or "")
    method = payment_method or ("COD" if result.get("action") == "hold_cod_order" else None)
    out = dict(result)
    out.update({"applied": [], "enforcement_error": None})
    try:
        if decision == "accept":
            step = record_decision(order_id, db, "accept", reason)
        elif decision == "void_discount":
            step = void_discount(order_id, db, reason)
        elif decision == "hold":
            step = (hold_cod_order if str(method or "").upper() == "COD" else hold_order)(order_id, db, reason)
        elif decision == "reject":
            step = reject_order(order_id, db, reason)
        else:
            raise EnforcementError(f"unknown decision {decision!r}")
        out["applied"].append(step["action"] if step["action"] != "none" else "record_decision")
    except Exception as exc:
        return _held_after_failure(result, order_id, db, method, f"{exc.__class__.__name__}: {exc}")

    action_account = result.get("account_action")
    if action_account:
        try:
            if not isinstance(action_account, dict) or action_account.get("type") != "rate_limit":
                raise EnforcementError(f"unknown account action {action_account!r}")
            rate_limit_account(account_id, db, action_account.get("minutes", 30), reason)
            out["applied"].append("rate_limit_account")
        except Exception as exc:
            # the order is already BLOCKED (stricter than hold), so the decision stays reject
            out["enforcement_error"] = _short(f"{exc.__class__.__name__}: {exc}", 200)
            out["reason"] = _short(reason + " (account rate limit could not be saved)", 500)
    return out
