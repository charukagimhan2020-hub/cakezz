"""Supabase REST helper for c1 (service key, JSON). Every database access in RuleLock goes through here."""
import logging
import uuid
from datetime import datetime, timedelta, timezone

import requests

import config

logger = logging.getLogger(__name__)


def _request(table, method="post", params=None, payload=None, headers=None):
    if not config.SUPABASE_URL or not config.SUPABASE_SECRET_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be configured")
    response = requests.request(
        method,
        f"{config.SUPABASE_URL}/rest/v1/{table}",
        headers={
            "apikey": config.SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {config.SUPABASE_SECRET_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
            **(headers or {}),
        },
        params=params,
        json=payload,
        timeout=5,
    )
    response.raise_for_status()
    return response.json() if response.content else []


def check_supabase():
    """Small authenticated read for /ready."""
    return _request("transaction_events", method="get", params={"select": "event_id", "limit": "1"})


# ---------- catalog and coupons ----------
def get_catalog():
    """Active products as {"sku-<id>": {name, price, sizes}} (the shape c2 and c4 expect)."""
    try:
        rows = _request("products", method="get", params={"select": "id,name,base_price,active,sizes", "active": "eq.true", "order": "id.asc"})
    except (RuntimeError, requests.RequestException):
        rows = _request("products", method="get", params={"select": "id,name,base_price,active", "active": "eq.true", "order": "id.asc"})
    return {f"sku-{row['id']}": {"name": row["name"], "price": float(row["base_price"]), "sizes": row.get("sizes")} for row in rows}


def get_coupon_percents():
    rows = _request("coupons", method="get", params={"select": "code,percent"})
    return {str(row["code"]).upper(): float(row["percent"]) for row in rows}


# ---------- accounts and orders ----------
def get_account_profile(user_id):
    """Live username, account age and completed-order count (no phone or address)."""
    if user_id is None:
        raise ValueError("user_id is required")
    rows = _request("users", method="get", params={"select": "id,username,created_at", "id": f"eq.{user_id}", "limit": "1"})
    if not rows:
        return {"user_id": user_id, "username": None, "account_age_days": 0, "completed_orders": 0}
    user = rows[0]
    created = datetime.fromisoformat(str(user["created_at"]).replace("Z", "+00:00"))
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    completed = _count_rows("orders", {"user_id": f"eq.{user_id}", "status": "eq.COMPLETED"})
    return {"user_id": user_id, "username": user.get("username"),
            "account_age_days": max(0, (datetime.now(timezone.utc) - created).days), "completed_orders": completed}


def get_usernames(user_ids):
    ids = [str(v) for v in user_ids if v is not None and str(v).isdigit()]
    if not ids:
        return {}
    rows = _request("users", method="get", params={"select": "id,username", "id": f"in.({','.join(ids)})", "limit": str(len(ids))})
    return {str(r["id"]): r.get("username") for r in rows}


def get_cod_history(user_id, exclude_order_id=None):
    """Earlier COD orders of the account and how many were bad (REFUSED, or CANCELLED by the customer)."""
    if user_id is None:
        raise ValueError("user_id is required")
    params = {"select": "id,status,cancelled_by", "user_id": f"eq.{user_id}", "payment_method": "eq.COD", "limit": "10000"}
    if exclude_order_id is not None:
        params["id"] = f"neq.{exclude_order_id}"
    rows = _request("orders", method="get", params=params)
    bad = sum(1 for r in rows if r.get("status") == "REFUSED" or (r.get("status") == "CANCELLED" and r.get("cancelled_by") == "CUSTOMER"))
    return {"total": len(rows), "bad": bad}


def get_used_coupons(user_id):
    """Coupon codes this account already used on earlier orders (recorded by the shop in coupons_used)."""
    if user_id is None:
        return []
    rows = _request("coupons_used", method="get", params={"select": "code", "user_id": f"eq.{int(user_id)}", "limit": "1000"})
    return [str(r["code"]).upper() for r in rows if r.get("code")]


def get_order_reference(order_id):
    rows = _request("orders", method="get", params={"select": "order_number", "id": f"eq.{order_id}", "limit": "1"})
    return str(rows[0]["order_number"]) if rows and rows[0].get("order_number") else None


def get_order_references(order_ids):
    ids = [str(v) for v in order_ids if v is not None]
    if not ids:
        return {}
    rows = _request("orders", method="get", params={"select": "id,order_number", "id": f"in.({','.join(ids)})", "limit": str(len(ids))})
    return {str(r["id"]): str(r["order_number"]) for r in rows if r.get("order_number")}


def get_order_id_by_reference(order_reference):
    rows = _request("orders", method="get", params={"select": "id", "order_number": f"eq.{order_reference}", "limit": "1"})
    return rows[0].get("id") if rows else None


def get_order_items(order_id):
    return _request("order_items", method="get", params={"select": "product_id,quantity,unit_price", "order_id": f"eq.{int(order_id)}", "order": "id.asc"})


def update_order(order_id, fields):
    """PATCH one order row. Raises when no row was changed, so enforcement can fail safe."""
    rows = _request("orders", method="patch", params={"id": f"eq.{int(order_id)}"}, payload=fields)
    if not rows:
        raise RuntimeError(f"order {order_id} not found")
    return rows[0]


def insert_restriction(user_id, type_, minutes, reason):
    until = datetime.now(timezone.utc) + timedelta(minutes=int(minutes))
    return _request("account_restrictions", payload={"user_id": int(user_id), "type": type_, "until": until.isoformat(), "reason": str(reason)[:300]})


# ---------- shopper events ----------
def insert_event(event_type, user_id, metadata):
    rows = _request("transaction_events", payload={"event_id": str(uuid.uuid4()), "event_type": event_type, "user_id": user_id, "metadata": metadata})
    return rows[0] if rows else {}


def get_session_events(session_id, minutes=30):
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return _request("transaction_events", method="get", params={
        "select": "event_type,created_at,user_id,metadata", "metadata->>session_id": f"eq.{session_id}",
        "created_at": f"gte.{since.isoformat()}", "order": "created_at.asc", "limit": "1000"})


def _get_metadata_events(field, value, hours=24, event_type=None, select="event_type,user_id,order_id,metadata"):
    if not value:
        return []
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    params = {"select": select, f"metadata->>{field}": f"eq.{value}", "created_at": f"gte.{since.isoformat()}",
              "order": "created_at.desc", "limit": "1000"}
    if event_type:
        params["event_type"] = f"eq.{event_type}"
    return _request("transaction_events", method="get", params=params)


def get_device_events(device_id, hours=24):
    return _get_metadata_events("device_id", device_id, hours=hours)


def get_phone_events(phone_hash, hours=24):
    return _get_metadata_events("phone_hash", phone_hash, hours=hours)


def get_coupon_review_count(account_id, hours=24):
    """Live reviews in the last 24 h for this account that had a coupon (the current order is not stored yet)."""
    rows = _get_metadata_events("account_id", account_id, hours=hours, event_type="RULELOCK_REVIEW", select="event_id,metadata")
    return sum(bool((r.get("metadata") or {}).get("coupons_applied")) for r in rows)


# ---------- reviews and audit ----------
def get_review_event(order_id, event_type="RULELOCK_REVIEW"):
    rows = _request("transaction_events", method="get", params={
        "select": "event_id,event_type,created_at,user_id,order_id,metadata", "event_type": f"eq.{event_type}",
        "order_id": f"eq.{order_id}", "order": "created_at.desc", "limit": "1"})
    return rows[0] if rows else None


def get_latest_review_event():
    rows = _request("transaction_events", method="get", params={
        "select": "event_id,event_type,created_at,user_id,order_id,metadata", "event_type": "eq.RULELOCK_REVIEW",
        "order": "created_at.desc", "limit": "1"})
    return rows[0] if rows else None


def insert_review_record(event, audit):
    """Atomically store the transaction event and its immutable audit row (team RPC record_rulelock_review)."""
    return _request("rpc/record_rulelock_review", payload={"p_event": event, "p_audit": audit})


def insert_audit_row(audit):
    """Insert an audit row; a repeat for the same event_id is ignored."""
    return _request("rulelock_audit_log", params={"on_conflict": "event_id"}, payload=audit,
                    headers={"Prefer": "resolution=ignore-duplicates,return=representation"})


def get_audit_log(action=None, search=None, cursor=None, limit=50, start=None, end=None):
    """Filter and paginate in PostgREST before the rows are limited. Live reviews only (no simulations)."""
    params = {
        "select": "audit_id,event_id,event_type,created_at,order_id,action,decision,reason,rule_code,anomaly_score,order_reference,account_id,payment_method,total",
        "event_type": "eq.RULELOCK_REVIEW", "order": "audit_id.desc", "limit": str(limit + 1),
    }
    if action and action != "ALL":
        params["action"] = f"eq.{action}"
    if cursor is not None:
        params["audit_id"] = f"lt.{int(cursor)}"
    if start is not None or end is not None:
        clauses = []
        if start is not None:
            clauses.append(f"created_at.gte.{start.isoformat()}")
        if end is not None:
            clauses.append(f"created_at.lt.{end.isoformat()}")
        params["and"] = f"({','.join(clauses)})"
    if search:
        term = "".join(ch for ch in search[:80] if ch.isalnum() or ch in " -_./")
        if term:
            clauses = [f"{field}.ilike.*{term}*" for field in ("order_reference", "account_id", "rule_code", "reason")]
            if term.isdigit():
                clauses.append(f"order_id.eq.{term}")
            params["or"] = f"({','.join(clauses)})"
    return _request("rulelock_audit_log", method="get", params=params)


def _count_rows(table, params):
    if not config.SUPABASE_URL or not config.SUPABASE_SECRET_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be configured")
    response = requests.get(
        f"{config.SUPABASE_URL}/rest/v1/{table}",
        headers={"apikey": config.SUPABASE_SECRET_KEY, "Authorization": f"Bearer {config.SUPABASE_SECRET_KEY}",
                 "Prefer": "count=exact", "Range": "0-0"},
        params={**params, "select": "*"}, timeout=5)
    response.raise_for_status()
    return int(response.headers.get("Content-Range", "*/0").rsplit("/", 1)[-1])


def count_audit_events(start, end, blocked_only=False):
    params = {"event_type": "eq.RULELOCK_REVIEW", "and": f"(created_at.gte.{start.isoformat()},created_at.lt.{end.isoformat()})"}
    if blocked_only:
        params["decision"] = "in.(hold,reject)"
    return _count_rows("rulelock_audit_log", params)


def count_transaction_events(event_type, start, end):
    return _count_rows("transaction_events", {"event_type": f"eq.{event_type}",
                                              "and": f"(created_at.gte.{start.isoformat()},created_at.lt.{end.isoformat()})"})


# ---------- toggle ----------
def get_rulelock_setting():
    try:
        rows = _request("platform_settings", method="get", params={"select": "id,rulelock_enabled,updated_at", "order": "id.asc", "limit": "1"})
    except (RuntimeError, requests.RequestException):
        logger.exception("Could not read the RuleLock setting")
        return None
    return rows[0] if rows else None


def set_rulelock_setting(enabled):
    setting = get_rulelock_setting()
    payload = {"rulelock_enabled": bool(enabled), "updated_at": datetime.now(timezone.utc).isoformat()}
    if setting:
        rows = _request("platform_settings", method="patch", params={"id": f"eq.{setting['id']}"}, payload=payload)
    else:
        rows = _request("platform_settings", payload={"id": 1, **payload})
    return rows[0] if rows else {"rulelock_enabled": bool(enabled)}
