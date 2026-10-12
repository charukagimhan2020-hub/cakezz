"""Test helpers for c1: an in-memory fake of the `db` module (no Supabase) and a tiny attribute patcher."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import paths  # noqa: E402,F401

# Train the c3 model once into a temp file (the repo never contains model.joblib).
import train_model  # noqa: E402  (c3)

_TMP = tempfile.mkdtemp()
MODEL_FILE = os.path.join(_TMP, "model.joblib")
train_model.train(MODEL_FILE)
os.environ["MODEL_PATH"] = MODEL_FILE

import config  # noqa: E402
import routes.events as events  # noqa: E402
from app import app  # noqa: E402

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class Patch:
    """with Patch(obj, name=value, ...): temporarily set attributes (works without pytest's monkeypatch)."""
    def __init__(self, obj, **attrs):
        self.obj, self.attrs, self.old = obj, attrs, {}

    def __enter__(self):
        for k, v in self.attrs.items():
            self.old[k] = getattr(self.obj, k)
            setattr(self.obj, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            setattr(self.obj, k, v)


class Setup:
    """Installs a FakeStore and the auth config for one test: `with Setup(store) as client:`"""
    def __init__(self, store, token=TOKEN, allow_no_auth=False):
        self.store, self.token, self.allow = store, token, allow_no_auth

    def __enter__(self):
        self.patches = [Patch(events, db=self.store),
                        Patch(config, RULELOCK_API_TOKEN=self.token, RULELOCK_ALLOW_NO_AUTH=self.allow)]
        for p in self.patches:
            p.__enter__()
        return app.test_client()

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.__exit__(*exc)


def iso(seconds_ago):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


class FakeStore:
    """Same function names as db.py. `fail` = names of functions that must raise."""
    def __init__(self):
        self.catalog = {"sku-1": {"name": "Choc cake", "price": 3500.0, "sizes": None},
                        "sku-2": {"name": "Cupcakes", "price": 1200.0, "sizes": None}}
        self.coupons = {"CAKE50": 50.0, "CAKE20": 20.0, "CAKE10": 10.0}
        self.profile = {"user_id": 7, "username": "kamal", "account_age_days": 30, "completed_orders": 2}
        self.cod = {"total": 0, "bad": 0}
        self.session_rows, self.device_rows, self.phone_rows = [], [], []
        self.coupon_reviews = 0
        self.used_coupons = []
        self.orders = {}          # order_id -> fields written by enforcement
        self.items = {}           # order_id -> rows
        self.reviews = {}         # (event_type, order_id) -> event dict
        self.audit_rows, self.restrictions, self.events = [], [], []
        self.setting = None
        self.fail = set()
        self.calls = {}

    def _call(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1
        if name in self.fail:
            raise RuntimeError(f"{name} failed")

    def add_order(self, order_id, items=None):
        self.orders[order_id] = {"status": "PENDING"}
        self.items[order_id] = items if items is not None else [{"product_id": 1, "quantity": 2, "unit_price": 3500}]

    # --- reads used by the pipeline
    def get_catalog(self):
        self._call("get_catalog"); return self.catalog

    def get_coupon_percents(self):
        self._call("get_coupon_percents"); return self.coupons

    def get_account_profile(self, user_id):
        self._call("get_account_profile"); return dict(self.profile, user_id=user_id)

    def get_cod_history(self, user_id, exclude_order_id=None):
        self._call("get_cod_history"); return dict(self.cod)

    def get_coupon_review_count(self, account_id):
        self._call("get_coupon_review_count"); return self.coupon_reviews

    def get_used_coupons(self, user_id):
        self._call("get_used_coupons"); return list(self.used_coupons)

    def get_session_events(self, session_id):
        self._call("get_session_events"); return self.session_rows

    def get_device_events(self, device_id):
        self._call("get_device_events"); return self.device_rows

    def get_phone_events(self, phone_hash):
        self._call("get_phone_events"); return self.phone_rows

    # --- enforcement writes
    def get_order_items(self, order_id):
        self._call("get_order_items"); return self.items.get(order_id, [])

    def update_order(self, order_id, fields):
        self._call("update_order")
        if order_id not in self.orders:
            raise RuntimeError(f"order {order_id} not found")
        self.orders[order_id].update(fields)

    def insert_restriction(self, user_id, type_, minutes, reason):
        self._call("insert_restriction")
        self.restrictions.append({"user_id": user_id, "type": type_, "minutes": minutes, "reason": reason})

    def insert_audit_row(self, audit):
        self._call("insert_audit_row")
        if not any(a["event_id"] == audit["event_id"] for a in self.audit_rows):
            self.audit_rows.append(audit)

    # --- reviews
    def get_order_reference(self, order_id):
        self._call("get_order_reference"); return f"CZ-REF-{order_id}"

    def get_review_event(self, order_id, event_type="RULELOCK_REVIEW"):
        self._call("get_review_event"); return self.reviews.get((event_type, order_id))

    def get_latest_review_event(self):
        self._call("get_latest_review_event")
        live = [e for (t, _), e in self.reviews.items() if t == "RULELOCK_REVIEW"]
        return live[-1] if live else None

    def insert_review_record(self, event, audit):
        self._call("insert_review_record")
        key = (event["event_type"], event["order_id"])
        if key in self.reviews:
            raise RuntimeError("duplicate review")
        self.reviews[key] = dict(event, created_at=iso(0))
        self.audit_rows.append(audit)

    def insert_event(self, event_type, user_id, metadata):
        self._call("insert_event")
        row = {"event_id": f"ev-{len(self.events) + 1}", "event_type": event_type, "user_id": user_id, "metadata": metadata}
        self.events.append(row)
        return row

    def get_order_references(self, ids):
        return {str(i): f"CZ-REF-{i}" for i in ids}

    def get_order_id_by_reference(self, reference):
        self._call("get_order_id_by_reference")
        for (_, oid), e in self.reviews.items():
            if (e["metadata"] or {}).get("order_reference") == reference:
                return oid
        return None

    def get_usernames(self, ids):
        return {str(i): "kamal" for i in ids if i is not None}

    # --- other endpoints
    def get_audit_log(self, **kwargs):
        self._call("get_audit_log"); return self.audit_rows[:kwargs.get("limit", 50) + 1]

    def count_audit_events(self, start, end, blocked_only=False):
        return len([a for a in self.audit_rows if not blocked_only or a["decision"] in ("hold", "reject")])

    def count_transaction_events(self, event_type, start, end):
        return 0

    def get_rulelock_setting(self):
        self._call("get_rulelock_setting"); return self.setting

    def set_rulelock_setting(self, enabled):
        self._call("set_rulelock_setting")
        self.setting = {"id": 1, "rulelock_enabled": enabled}
        return self.setting

    def check_supabase(self):
        self._call("check_supabase"); return []


def clean_order(order_id=101, **over):
    """What the shop sends for an honest order: 2 x sku-1 at 3500, card, no coupon."""
    body = {"order_id": order_id, "order_reference": f"CZ-2026{order_id}", "user_id": 7, "customer_name": "kamal",
            "session_id": "sess-1", "device_id": "dev-1", "phone_hash": "ph-1", "address_hash": "ad-1",
            "payment_method": "CARD", "items": [{"sku": "sku-1", "quantity": 2, "unit_price": 3500}],
            "coupons_applied": [], "subtotal": 7000, "discount_value": 0, "total": 7000}
    body.update(over)
    return body


def burst_rows(n=8, gap=1.0):
    """n APPLY_COUPON events of one session, `gap` seconds apart, ending now."""
    return [{"event_type": "APPLY_COUPON", "created_at": iso((n - 1 - i) * gap), "user_id": 7,
             "metadata": {"session_id": "sess-1", "device_id": "dev-1", "phone_hash": "ph-1", "address_hash": "ad-1"}}
            for i in range(n)]
