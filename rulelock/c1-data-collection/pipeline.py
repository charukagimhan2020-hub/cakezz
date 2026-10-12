"""c1 orchestrator: build the inputs, call c2 (rules), c3 (anomaly), c4 (decision + enforcement), build the `pipeline` object.

Every step is wrapped. A step that fails gets status "error" plus an error text in `pipeline`, and the final decision
becomes `hold` (or stays reject): a failure never ends in accept or void_discount.
"""
import paths  # noqa: F401  (sys.path for c2, c3, c4)

import logging
import re

import features as c3_features            # c3
import scoring as c3_scoring              # c3
from actions import apply_enforcement     # c4
from decision import action_for, customer_message_for, decide, payment_action_for, thresholds   # c4
from rules import validate_transaction    # c2

from adapter import StoreEnforcementDb

logger = logging.getLogger(__name__)

FEATURE_NAMES = c3_features.FEATURE_NAMES
DECISIONS = ("accept", "void_discount", "hold", "reject")


def bigint(value):
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, float) and not value.is_integer():
            return None
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _clean_error(exc):
    text = f"{exc.__class__.__name__}: {exc}"
    return re.sub(r"https?://\S+", "<url>", text)[:200]


def _step(name, fn):
    try:
        return fn(), None
    except Exception as exc:
        logger.exception("Pipeline step %s failed", name)
        return None, _clean_error(exc)


def _meta(row):
    return (row or {}).get("metadata") or {}


# ---------- c1: session features ----------
def compute_session_features(session_rows, device_rows, phone_rows, now=None):
    """The four model features, counted like this (README.md):
       coupon_attempts_per_session    APPLY_COUPON events of the session in the last 30 minutes
       avg_seconds_between_requests   (last - first) / (n - 1) over the session events of the last 30 minutes, default 30 if n < 3
       distinct_accounts_same_device  different user_id on events with this device_id in the last 24 h (at least 1)
       distinct_addresses_same_phone  different address_hash on events with this phone_hash in the last 24 h (at least 1)"""
    recent = c3_features.recent_session_events(session_rows, now)
    device_rows = [r for r in device_rows or [] if isinstance(r, dict)]
    phone_rows = [r for r in phone_rows or [] if isinstance(r, dict)]
    accounts = {str(_meta(r).get("account_id") if _meta(r).get("account_id") is not None else r.get("user_id"))
                for r in device_rows
                if _meta(r).get("account_id") is not None or r.get("user_id") is not None}
    addresses = {_meta(r).get("address_hash") for r in phone_rows if _meta(r).get("address_hash")}
    return {
        "event_count": len(recent),
        "coupon_attempts_per_session": sum(r.get("event_type") == "APPLY_COUPON" for _, r in recent),
        "avg_seconds_between_requests": c3_features.average_seconds_between_requests(session_rows, now),
        "distinct_accounts_same_device": max(len(accounts), 1),
        "distinct_addresses_same_phone": max(len(addresses), 1),
    }


def _default_features():
    return {"event_count": 0, **c3_features.FEATURE_DEFAULTS}


def collect_inputs(body, store, order_id, now=None):
    """Everything c2 and c3 need. Any failure raises (the caller turns it into a hold)."""
    user_id = bigint(body.get("user_id"))
    account_id = str(user_id) if user_id is not None else str(body.get("account_id") or "")
    payment_method = str(body.get("payment_method", "CARD")).upper()
    simulation = body.get("simulation") is True
    simulated = body.get("simulated_account") if isinstance(body.get("simulated_account"), dict) else {}

    session_id, device_id, phone_hash = body.get("session_id"), body.get("device_id"), body.get("phone_hash")
    session_rows = store.get_session_events(session_id) if session_id else []
    session_rows = session_rows or []
    device_id = device_id or next((_meta(r).get("device_id") for r in session_rows if _meta(r).get("device_id")), None)
    phone_hash = phone_hash or next((_meta(r).get("phone_hash") for r in session_rows if _meta(r).get("phone_hash")), None)
    device_rows = store.get_device_events(device_id) if device_id else []
    phone_rows = store.get_phone_events(phone_hash) if phone_hash else []
    features = compute_session_features(session_rows, device_rows, phone_rows, now) if session_id else _default_features()

    if simulation:
        total, bad = int(simulated.get("cod_orders", 0) or 0), int(simulated.get("cod_bad", 0) or 0)
        profile = {"user_id": user_id, "username": body.get("customer_name") or "Simulation account",
                   "account_age_days": int(simulated.get("account_age_days", 0) or 0),
                   "completed_orders": int(simulated.get("completed_orders", 0) or 0)}
        coupon_count = simulated.get("coupon_reviews_24h")
        used_coupons = simulated.get("used_coupons") if isinstance(simulated.get("used_coupons"), list) else []
    else:
        profile = store.get_account_profile(user_id) if user_id is not None else {
            "user_id": None, "username": None, "account_age_days": 0, "completed_orders": 0}
        if payment_method == "COD":
            if user_id is None:
                raise ValueError("a COD review needs a user_id to load the account history")
            history = store.get_cod_history(user_id, order_id)
            total, bad = history["total"], history["bad"]
        else:
            total, bad = 0, 0
        coupons = body.get("coupons_applied")
        coupon_count = store.get_coupon_review_count(account_id) if coupons and account_id else None
        used_coupons = store.get_used_coupons(user_id) if coupons and user_id is not None else []
    profile = {**profile, "cod_orders": total, "cod_bad_orders": bad}
    return {"features": features, "profile": profile, "history": {"total": total, "bad": bad},
            "catalog": store.get_catalog(), "coupon_percents": store.get_coupon_percents(), "coupon_count": coupon_count,
            "used_coupons": used_coupons}


# ---------- pipeline object ----------
def _anomaly_status(score):
    if score is None:
        return "error"
    t = thresholds()
    return "high_risk" if score < t["reject"] else "suspicious" if score < t["hold"] else "normal"


def _force_hold(result, payment_method, reason):
    return {"decision": "hold", "reason": reason, "rule_code": result.get("rule_code"),
            "action": action_for("hold", payment_method), "account_action": None}


def _build_pipeline(features, profile, rule, rule_err, score, score_err, result, c1_err, enforcement_err, skipped):
    t = thresholds()
    c1 = {"status": "error" if c1_err else "complete", "events_in_session": int(features.get("event_count", 0) or 0),
          "session_features": {n: features.get(n, c3_features.FEATURE_DEFAULTS[n]) for n in FEATURE_NAMES}, "account": profile}
    if c1_err:
        c1["error"] = c1_err
    if rule is not None:
        c2 = {"status": "pass" if rule.get("passed") else "fail", "checks": rule.get("checks", []), "violations": rule.get("violations", [])}
    else:
        c2 = {"status": "skipped" if skipped else "error", "checks": [], "violations": []}
        if rule_err:
            c2["error"] = rule_err
    c3 = {"status": "skipped" if skipped else _anomaly_status(score), "score": score,
          "hold_threshold": t["hold"], "reject_threshold": t["reject"]}
    if score_err:
        c3["error"] = score_err
    c4 = {"decision": result["decision"], "action": result.get("action"), "reason": result["reason"],
          "account_action": result.get("account_action")}
    if enforcement_err:
        c4["error"] = enforcement_err
    return {"c1_data_collection": c1, "c2_rule_engine": c2, "c3_anomaly": c3, "c4_enforcement": c4}


def _response(order_id, order_reference, result, pipeline):
    decision = result["decision"] if result["decision"] in DECISIONS else "hold"
    return {"order_id": order_id, "order_reference": order_reference, "decision": decision, "reason": result["reason"],
            "customer_message": customer_message_for(decision), "payment_action": payment_action_for(decision),
            "account_action": result.get("account_action"), "pipeline": pipeline, "rulelock_enabled": True}


def fallback_response(order_id, order_reference, reason, error=None):
    """A hold for when the review itself cannot run or be stored. Same shape as a normal response."""
    result = {"decision": "hold", "reason": reason, "rule_code": None, "action": "hold_order", "account_action": None}
    pipeline = _build_pipeline(_default_features(), {}, None, error, None, error, result, error, None, skipped=False)
    return _response(order_id, order_reference, result, pipeline)


def run_review(body, store, order_id, order_reference, simulation=False, now=None):
    """Returns (response, info). `response` follows CONTRACT.md. `info` = {rule_code, anomaly_score, account_id}.
    The browser values in `body` reach c2 untouched (only the account fields are added, from our own data)."""
    user_id = bigint(body.get("user_id"))
    account_id = str(user_id) if user_id is not None else str(body.get("account_id") or "")
    method = str(body.get("payment_method", "CARD")).upper()
    errors = []

    inputs, c1_err = _step("c1", lambda: collect_inputs(body, store, order_id, now))
    if c1_err:
        errors.append(("data collection", c1_err))
    features = inputs["features"] if inputs else _default_features()
    profile = inputs["profile"] if inputs else {}

    rule, rule_err, score, score_err = None, None, None, None
    if inputs:
        payload = dict(body)
        payload.update(account_verified=profile.get("completed_orders", 0) >= 1,
                       past_orders=inputs["history"]["total"], past_refusals=inputs["history"]["bad"],
                       used_coupons=inputs["used_coupons"])
        rule, rule_err = _step("c2", lambda: validate_transaction(
            payload, catalog=inputs["catalog"], coupon_review_count=inputs["coupon_count"], coupon_percents=inputs["coupon_percents"]))
        if rule is not None and not isinstance(rule, dict):
            rule, rule_err = None, "TypeError: rule engine returned no result"
        if rule_err:
            errors.append(("rule engine", rule_err))
        scored, score_err = _step("c3", lambda: c3_scoring.score_session({n: features[n] for n in FEATURE_NAMES}))
        if score_err:
            errors.append(("anomaly detection", score_err))
        else:
            score = float(scored[0])

    rule_ok = bool(rule and rule.get("passed"))
    rule_reason = "; ".join(rule.get("failures", [])) if rule else "rule engine did not run"
    result, c4_err = _step("c4", lambda: decide(
        order_id=order_id, account_id=account_id, rule_passed=rule_ok, rule_reason=rule_reason, anomaly_score=score,
        payment_method=method, rule_code=(rule or {}).get("rule_code"), violations=(rule or {}).get("violations")))
    if c4_err:
        errors.append(("decision", c4_err))
        result = _force_hold({}, method, "decision step failed; order held for safety")

    # a failed step may never lead to accept or void_discount
    if errors and result["decision"] in ("accept", "void_discount"):
        step, text = errors[0]
        result = _force_hold(result, method, f"{step} step failed ({text}); order held for safety")

    enforcement_err = None
    if not simulation:
        applied, enf_exc = _step("c4_apply", lambda: apply_enforcement(result, order_id, account_id, StoreEnforcementDb(store), payment_method=method))
        if enf_exc:
            enforcement_err = enf_exc
            result = _force_hold(result, method, f"enforcement failed ({enf_exc}); order held for safety")
        else:
            result = {k: applied.get(k) for k in ("decision", "reason", "rule_code", "action", "account_action")}
            enforcement_err = applied.get("enforcement_error")

    pipeline = _build_pipeline(features, profile, rule, rule_err, score, score_err, result, c1_err, enforcement_err or c4_err, skipped=bool(c1_err))
    response = _response(order_id, order_reference, result, pipeline)
    return response, {"rule_code": result.get("rule_code"), "anomaly_score": score, "account_id": account_id}
