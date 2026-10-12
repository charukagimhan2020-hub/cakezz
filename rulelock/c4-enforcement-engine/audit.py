"""c4 audit: build the minimal, insert-only payload for the `rulelock_audit_log` table.

No customer name, phone, address, or raw request goes in. The columns follow the team's migration
data-collection/migrations/2026-10-03_rulelock_audit_log.sql. c1 owns the connection: it stores the row with its
`record_rulelock_review` RPC, or `record(db, payload)` calls `db.insert_audit(payload)`. There is deliberately no
update or delete helper (the table also rejects them with a trigger).
"""
import math
import uuid
from datetime import datetime, timezone

EVENT_TYPES = ("RULELOCK_REVIEW", "RULELOCK_SIMULATION")
ACTION_LABEL = {"accept": "PASS", "void_discount": "VOID", "hold": "HOLD", "reject": "REJECT"}
COLUMNS = ("event_id", "event_type", "order_id", "created_at", "action", "decision", "reason",
           "order_reference", "account_id", "payment_method", "total", "rule_code", "anomaly_score")


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _text(value, limit):
    return None if value is None else str(value)[:limit]


def build_audit_payload(result, order_id, account_id=None, payment_method=None, total=None, order_reference=None,
                        anomaly_score=None, event_type="RULELOCK_REVIEW", event_id=None, created_at=None):
    """Minimal audit row for one decision. `result` is decide()'s (or apply_enforcement()'s) dict."""
    result = result or {}
    if event_type not in EVENT_TYPES:
        raise ValueError(f"event_type must be one of {EVENT_TYPES}")
    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        raise ValueError("order_id must be a whole number")
    decision = str(result.get("decision") or "hold")
    payload = {
        "event_id": str(event_id or uuid.uuid4()),
        "event_type": event_type,
        "order_id": order_id,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "action": ACTION_LABEL.get(decision, "HOLD"),
        "decision": decision,
        "reason": _text(result.get("reason") or "", 1000),
        "order_reference": _text(order_reference, 200),
        "account_id": _text(account_id, 200),
        "payment_method": _text(payment_method, 40),
        "total": _number(total),
        "rule_code": _text(result.get("rule_code"), 100),
        "anomaly_score": _number(anomaly_score),
    }
    return {k: payload[k] for k in COLUMNS}


def record(db, payload):
    """Insert-only: hand the payload to the injected db. Raises if the insert fails (c1 decides what to do)."""
    db.insert_audit(payload)
    return payload
