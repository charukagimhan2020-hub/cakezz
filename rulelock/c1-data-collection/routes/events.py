"""c1 HTTP routes: POST /events, POST /review-order, audit APIs, toggle APIs, dashboard summary, pipeline info."""
import paths  # noqa: F401

import hmac
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from requests import RequestException

import config
import db
import pipeline
import rules as c2_rules                    # c2 (settings only, for /pipeline/info)
import scoring as c3_scoring                # c3
from audit import build_audit_payload       # c4
from decision import thresholds             # c4

bp = Blueprint("events", __name__)
logger = logging.getLogger(__name__)

EVENT_TYPES = {"LOGIN", "BROWSE", "ADD_TO_CART", "APPLY_COUPON", "CHECKOUT"}
RESERVED_META = {"session_id", "device_id", "phone_hash", "address_hash"}
CONTRACT_KEYS = ("order_id", "order_reference", "decision", "reason", "customer_message", "payment_action",
                 "account_action", "pipeline", "rulelock_enabled")


def _authorized_request():
    if not config.RULELOCK_API_TOKEN:
        return config.RULELOCK_ALLOW_NO_AUTH
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(token, config.RULELOCK_API_TOKEN)


def _unauthorized():
    return jsonify(error="invalid RuleLock authorization"), 401


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _text(value, limit):
    return None if value is None else str(value)[:limit]


# ---------- POST /events ----------
@bp.post("/events")
def post_event():
    """Store one shopper event. Features for the anomaly model are built from these rows."""
    if not _authorized_request():
        return _unauthorized()
    if (request.content_length or 0) > config.EVENT_MAX_BYTES:
        return jsonify(error=f"event body is larger than {config.EVENT_MAX_BYTES} bytes"), 413
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="send a JSON object"), 400
    event_type = body.get("event_type")
    if event_type not in EVENT_TYPES:
        return jsonify(error=f"unknown event_type; use one of {sorted(EVENT_TYPES)}"), 400
    session_id = body.get("session_id")
    if not isinstance(session_id, str) or not 1 <= len(session_id) <= 100:
        return jsonify(error="session_id is required (text, up to 100 characters)"), 400
    user_id = None
    if body.get("user_id") is not None:
        user_id = pipeline.bigint(body.get("user_id"))
        if user_id is None:
            return jsonify(error="user_id must be a whole number or null"), 400
    extra = body.get("metadata") or {}
    if not isinstance(extra, dict):
        return jsonify(error="metadata must be an object"), 400
    metadata = {k: v for k, v in extra.items() if k not in RESERVED_META and isinstance(k, str)}
    metadata.update(session_id=session_id, device_id=_text(body.get("device_id"), 100),
                    phone_hash=_text(body.get("phone_hash"), 128), address_hash=_text(body.get("address_hash"), 128))
    if user_id is not None:
        metadata["account_id"] = str(user_id)
    try:
        row = db.insert_event(event_type, user_id, metadata)
    except (RequestException, RuntimeError, ValueError):
        logger.exception("Could not store %s event", event_type)
        return jsonify(error="could not store the event"), 503
    return jsonify(stored=True, event_id=row.get("event_id")), 201


# ---------- POST /review-order ----------
def _stored_response(meta, order_id, reference):
    """Rebuild the contract response from a stored review (idempotent retry)."""
    out = {k: meta.get(k) for k in CONTRACT_KEYS}
    out["order_id"] = meta.get("order_id", order_id)
    out["order_reference"] = meta.get("order_reference") or reference
    if out["decision"] not in pipeline.DECISIONS:
        out["decision"] = "hold"
    out["rulelock_enabled"] = True
    return out


def _audit_row(result, order_id, meta, event_type, event_id):
    return build_audit_payload(
        {"decision": result["decision"], "reason": result["reason"], "rule_code": meta.get("rule_code")}, order_id,
        meta.get("account_id"), meta.get("payment_method"), meta.get("total"), meta.get("order_reference"),
        meta.get("anomaly_score"), event_type=event_type, event_id=event_id)


@bp.post("/review-order")
def review_order():
    """Review one order before payment. Idempotent per order_id (and per event type)."""
    if not _authorized_request():
        return _unauthorized()
    if (request.content_length or 0) > config.MAX_BODY_BYTES:
        return jsonify(error=f"request body is larger than {config.MAX_BODY_BYTES} bytes"), 413
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="send a JSON object"), 400
    if not body.get("order_id"):
        return jsonify(error="order_id is required"), 400
    order_id = pipeline.bigint(body.get("order_id"))
    if order_id is None:
        return jsonify(error="order_id must be numeric"), 400

    simulation = body.get("simulation") is True
    event_type = "RULELOCK_SIMULATION" if simulation else "RULELOCK_REVIEW"
    supplied = body.get("order_reference") or body.get("order_ref") or body.get("external_order_id")
    if simulation:
        reference = f"SIM-{order_id}"
    elif supplied:
        reference = str(supplied)[:200]
    else:
        try:
            reference = db.get_order_reference(order_id) or str(order_id)
        except Exception:
            logger.exception("Could not look up the order reference for order %s", order_id)
            reference = str(order_id)

    # idempotency: a second call for the same order returns the stored review and changes nothing
    try:
        previous = db.get_review_event(order_id, event_type=event_type)
    except Exception:
        logger.exception("Could not check for an earlier review of order %s", order_id)
        return jsonify(pipeline.fallback_response(order_id, reference, "Review storage is temporarily unavailable", "storage unavailable")), 200
    if previous:
        meta = previous.get("metadata") or {}
        response = _stored_response(meta, order_id, reference)
        try:
            db.insert_audit_row(_audit_row(response, order_id, {**meta, "order_reference": meta.get("order_reference") or reference},
                                           event_type, previous.get("event_id")))
        except Exception:
            logger.exception("Could not reconcile the audit row for order %s", order_id)
            return jsonify(pipeline.fallback_response(order_id, reference, "Review storage is temporarily unavailable", "audit unavailable")), 200
        return jsonify(response), 200

    try:
        response, info = pipeline.run_review(body, db, order_id, reference, simulation=simulation)
    except Exception as exc:                      # last resort: the orchestrator itself must never break the shop
        logger.exception("Review pipeline crashed for order %s", order_id)
        response, info = pipeline.fallback_response(order_id, reference, "Review could not be completed", pipeline._clean_error(exc)), {}

    session_id = body.get("session_id")
    user_id = pipeline.bigint(body.get("user_id"))
    meta = {**response,
            "customer_name": _text(body.get("customer_name"), 100), "total": body.get("total"),
            "payment_method": str(body.get("payment_method", "CARD")).upper()[:40], "coupons_applied": body.get("coupons_applied", []),
            "session_id": session_id, "account_id": info.get("account_id") or (str(user_id) if user_id is not None else None),
            "rule_code": info.get("rule_code"), "anomaly_score": info.get("anomaly_score")}
    event_id = str(uuid.uuid4())
    try:
        event = {"event_id": event_id, "event_type": event_type, "user_id": user_id, "order_id": order_id,
                 "metadata": {**meta, "session_id": session_id or ""}}
        db.insert_review_record(event, _audit_row(response, order_id, meta, event_type, event_id))
    except Exception:
        logger.exception("Could not store the review of order %s", order_id)
        try:
            earlier = db.get_review_event(order_id, event_type=event_type)          # a concurrent request may have won
            if earlier:
                return jsonify(_stored_response(earlier.get("metadata") or {}, order_id, reference)), 200
        except Exception:
            logger.exception("Could not read back the review of order %s", order_id)
        if response["decision"] != "reject":                                        # never let a storage problem become accept
            response = pipeline.fallback_response(order_id, reference, "Review could not be stored; order held for safety", "storage failed")
    return jsonify(response), 200


# ---------- audit APIs ----------
def _review_detail(event):
    meta = event.get("metadata") or {}
    order_id = event.get("order_id")
    reference = meta.get("order_reference")
    if not reference:
        try:
            reference = db.get_order_reference(order_id)
        except Exception:
            logger.exception("Could not resolve the order reference for order %s", order_id)
    pipe = meta.get("pipeline")
    account = (pipe or {}).get("c1_data_collection", {}).get("account", {})
    return {"order_id": order_id, "order_reference": reference or str(order_id), "created_at": event.get("created_at"),
            "customer_name": meta.get("customer_name") or account.get("username"), "account_username": account.get("username"),
            "decision": meta.get("decision"), "reason": meta.get("reason"), "customer_message": meta.get("customer_message"),
            "payment_action": meta.get("payment_action"), "account_action": meta.get("account_action"),
            "payment_method": meta.get("payment_method"), "total": meta.get("total"), "coupons_applied": meta.get("coupons_applied"),
            "pipeline": pipe, "account": account}


@bp.get("/audit-log")
def audit_log():
    if not _authorized_request():
        return _unauthorized()
    action_filter = request.args.get("action")
    search = request.args.get("search", "").strip()
    cursor = request.args.get("cursor")
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
    except (TypeError, ValueError):
        limit = 50
    if cursor is not None and not cursor.isdigit():
        return jsonify(error="cursor must be a numeric audit ID"), 400
    try:
        rows = db.get_audit_log(action=action_filter, search=search, cursor=cursor, limit=limit) or []
    except (RequestException, RuntimeError):
        rows = []
    has_more = len(rows) > limit
    page = rows[:limit]
    try:
        references = db.get_order_references([r.get("order_id") for r in page if not r.get("order_reference")])
    except Exception:
        logger.exception("Could not backfill audit order references")
        references = {}
    entries = [{
        "action_id": f"ACT-{r.get('event_id')}", "timestamp": r.get("created_at"), "action": r.get("action"),
        "decision": r.get("decision"), "reason": r.get("reason", ""), "rule_violated": r.get("rule_code"),
        "score": r.get("anomaly_score"), "order_id": r.get("order_id"),
        "order_reference": r.get("order_reference") or references.get(str(r.get("order_id"))) or str(r.get("order_id")),
        "account_id": r.get("account_id"), "payment_method": r.get("payment_method"), "total": r.get("total"),
    } for r in page]
    try:
        names = db.get_usernames([e.get("account_id") for e in entries])
    except Exception:
        logger.exception("Could not resolve audit account usernames")
        names = {}
    for e in entries:
        e["account_username"] = names.get(str(e.get("account_id")))
    return jsonify({"records": entries, "count": len(entries), "next_cursor": page[-1].get("audit_id") if has_more and page else None}), 200


@bp.get("/audit-log/latest")
def audit_log_latest():
    """The newest live review with its full pipeline (the monitor tab polls this)."""
    if not _authorized_request():
        return _unauthorized()
    try:
        event = db.get_latest_review_event()
        if not event:
            return jsonify(error="no reviews yet"), 404
        return jsonify(_review_detail(event)), 200
    except (RequestException, RuntimeError, TypeError, ValueError):
        logger.exception("Could not load the latest review")
        return jsonify(error="review detail unavailable"), 503


@bp.get("/audit-log/<order_key>")
def audit_log_detail(order_key):
    """Full stored review (with `pipeline`) for one order, by numeric id or by order reference such as CZ-2026..."""
    if not _authorized_request():
        return _unauthorized()
    try:
        order_id = pipeline.bigint(order_key)
        if order_id is None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", order_key):
                return jsonify(error="review not found"), 404
            order_id = pipeline.bigint(db.get_order_id_by_reference(order_key))
        event = db.get_review_event(order_id) if order_id is not None else None
        if not event:
            return jsonify(error="review not found"), 404
        return jsonify(_review_detail(event)), 200
    except (RequestException, RuntimeError, TypeError, ValueError):
        logger.exception("Could not load the review for %s", order_key)
        return jsonify(error="review detail unavailable"), 503


# ---------- toggle ----------
@bp.get("/settings/rulelock")
def get_rulelock_toggle():
    if not _authorized_request():
        return _unauthorized()
    setting = db.get_rulelock_setting()
    enabled = False if setting is None else _as_bool(setting.get("rulelock_enabled"))
    return jsonify(rulelock_enabled=enabled, source="default" if setting is None else "platform_settings"), 200


@bp.post("/settings/rulelock")
def update_rulelock_toggle():
    if not _authorized_request():
        return _unauthorized()
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or "rulelock_enabled" not in body:
        return jsonify(error="rulelock_enabled is required"), 400
    try:
        setting = db.set_rulelock_setting(_as_bool(body["rulelock_enabled"]))
    except (RequestException, RuntimeError):
        logger.exception("Could not update the RuleLock setting")
        return jsonify(error="could not update the RuleLock setting"), 503
    return jsonify(rulelock_enabled=_as_bool(setting.get("rulelock_enabled")), source="platform_settings"), 200


# ---------- pipeline info ----------
@bp.get("/pipeline/info")
def pipeline_info():
    if not _authorized_request():
        return _unauthorized()
    info = c3_scoring.model_metadata()
    info["rule_thresholds"] = {
        "max_coupons": c2_rules.MAX_COUPONS, "max_discount_ratio": c2_rules.MAX_DISCOUNT_RATIO,
        "max_quantity_per_line": c2_rules.MAX_QUANTITY_PER_LINE, "min_purchase_amount": c2_rules.MIN_PURCHASE_AMOUNT,
        "price_match_tolerance": c2_rules.PRICE_MATCH_TOLERANCE, "total_tolerance": c2_rules.TOTAL_TOLERANCE,
        "cod_unverified_order_cap": c2_rules.COD_UNVERIFIED_ORDER_CAP, "cod_bad_hold": c2_rules.COD_BAD_HOLD,
        "cod_bad_reject": c2_rules.COD_BAD_REJECT, "cod_bad_ratio": c2_rules.COD_BAD_RATIO,
        "coupon_velocity_max_reviews": c2_rules.COUPON_VELOCITY_MAX_REVIEWS,
    }
    info["enforcement"] = thresholds()
    return jsonify(info), 200


# ---------- dashboard summary (from the audit table; simulations excluded) ----------
def _empty_summary():
    return {
        "threats_blocked": 0, "threats_blocked_delta": 0, "rule_violations": {"total": 0, "coupon": 0, "cod": 0},
        "anomaly_detections": 0, "discounts_voided": 0, "cod_orders_held": 0, "accounts_suspended": 0,
        "abuse_breakdown": {"coupon_discount_abuse": 0, "price_quantity_manipulation": 0, "cod_fake_order_abuse": 0},
        "enforcement_feed": [],
        "components": {
            "transaction_monitor": {"events_captured_24h": 0, "avg_latency": "n/a", "sessions_active": 0, "db_write_errors": 0},
            "rule_engine": {"requests_validated_24h": 0, "rule_violations": 0, "avg_validation_time": "n/a", "false_positives": "n/a"},
            "anomaly_detection": {"model": "Isolation Forest", "anomaly_threshold": "n/a", "precision": "n/a", "false_positive_rate": "n/a"},
            "enforcement_engine": {"actions_taken_24h": 0, "avg_decision_time": "n/a", "audit_log_entries": 0, "manual_overrides": 0},
        },
    }


@bp.get("/dashboard/summary")
def dashboard_summary():
    if not _authorized_request():
        return _unauthorized()
    summary = _empty_summary()
    try:
        now = datetime.now(timezone.utc)
        start, previous = now - timedelta(hours=24), now - timedelta(hours=48)
        rows = db.get_audit_log(limit=2000, start=start, end=now) or []
        total = db.count_audit_events(start, now)
        summary["threats_blocked"] = db.count_audit_events(start, now, blocked_only=True)
        summary["threats_blocked_delta"] = summary["threats_blocked"] - db.count_audit_events(previous, start, blocked_only=True)
        summary["components"]["enforcement_engine"]["manual_overrides"] = db.count_transaction_events("RULELOCK_OVERRIDE", start, now)
    except (RequestException, RuntimeError):
        logger.exception("Dashboard summary unavailable")
        return jsonify({**summary, "threats_blocked": "n/a", "threats_blocked_delta": "n/a", "rule_violations": "n/a",
                        "anomaly_detections": "n/a", "discounts_voided": "n/a", "cod_orders_held": "n/a", "abuse_breakdown": "n/a"}), 200
    coupon_codes = {"coupon_usage", "discount_range", "coupon_velocity", "minimum_purchase"}
    price_codes = {"quantity_ceiling", "price_mismatch", "total_mismatch"}
    coupon = cod = price = 0
    hold_threshold = thresholds()["hold"]
    try:
        names = db.get_usernames([r.get("account_id") for r in rows])
    except Exception:
        names = {}
    for r in rows:
        code, decision = r.get("rule_code"), r.get("decision")
        coupon += code in coupon_codes
        price += code in price_codes
        cod += bool(code and code.startswith("cod_"))
        score = r.get("anomaly_score")
        if isinstance(score, (int, float)) and score < hold_threshold:
            summary["anomaly_detections"] += 1
        summary["discounts_voided"] += decision == "void_discount"
        summary["cod_orders_held"] += bool(decision == "hold" and code and code.startswith("cod_"))
        summary["accounts_suspended"] += bool(decision == "reject" and not code)
        if len(summary["enforcement_feed"]) < 20:
            summary["enforcement_feed"].append({
                "timestamp": r.get("created_at"), "action": r.get("action"), "description": r.get("reason") or "RuleLock review completed",
                "order_id": r.get("order_id"), "order_reference": r.get("order_reference") or str(r.get("order_id")), "rule_code": code,
                "account_id": r.get("account_id"), "account_username": names.get(str(r.get("account_id"))), "total": r.get("total")})
    summary["rule_violations"] = {"total": coupon + cod + price, "coupon": coupon, "cod": cod}
    summary["abuse_breakdown"] = {"coupon_discount_abuse": coupon, "price_quantity_manipulation": price, "cod_fake_order_abuse": cod}
    comps = summary["components"]
    comps["transaction_monitor"].update({"events_captured_24h": total, "sessions_active": "n/a", "db_write_errors": "n/a"})
    comps["rule_engine"].update({"requests_validated_24h": total, "rule_violations": coupon + cod + price})
    comps["enforcement_engine"].update({"actions_taken_24h": summary["threats_blocked"], "audit_log_entries": total})
    return jsonify(summary), 200
