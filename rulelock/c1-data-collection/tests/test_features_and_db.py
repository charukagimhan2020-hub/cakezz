"""Session feature counting, the Supabase helper (HTTP layer mocked), and the c4 adapter."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from c1_helpers import FakeStore, Patch, iso, burst_rows

import adapter
import db
import pipeline


def row(event_type, seconds_ago, user_id=None, **meta):
    return {"event_type": event_type, "created_at": iso(seconds_ago), "user_id": user_id, "metadata": meta}


# ---------- features ----------
def test_features_are_counted_as_documented():
    session = [row("APPLY_COUPON", 40), row("APPLY_COUPON", 20), row("CHECKOUT", 0)]
    device = [row("LOGIN", 5, user_id=7), row("LOGIN", 5, user_id=8), row("LOGIN", 5, user_id=None, account_id="9"),
              row("BROWSE", 5, user_id=7), row("BROWSE", 5)]
    phone = [row("CHECKOUT", 5, address_hash="a1"), row("CHECKOUT", 5, address_hash="a2"), row("CHECKOUT", 5, address_hash="a1"),
             row("CHECKOUT", 5)]
    f = pipeline.compute_session_features(session, device, phone)
    assert f["coupon_attempts_per_session"] == 2 and f["event_count"] == 3
    assert 19 <= f["avg_seconds_between_requests"] <= 21
    assert f["distinct_accounts_same_device"] == 3 and f["distinct_addresses_same_phone"] == 2


def test_features_defaults_and_window():
    f = pipeline.compute_session_features([], [], [])
    assert f == {"event_count": 0, "coupon_attempts_per_session": 0, "avg_seconds_between_requests": 30,
                 "distinct_accounts_same_device": 1, "distinct_addresses_same_phone": 1}
    old = [row("APPLY_COUPON", 3600), row("APPLY_COUPON", 3500), row("APPLY_COUPON", 3400)]      # outside 30 minutes
    assert pipeline.compute_session_features(old, [], [])["coupon_attempts_per_session"] == 0
    assert pipeline.compute_session_features(burst_rows(2, 1.0), [], [])["avg_seconds_between_requests"] == 30   # fewer than 3 events


def test_features_ignore_broken_rows():
    f = pipeline.compute_session_features([None, {}, {"created_at": "garbage"}, {"event_type": "APPLY_COUPON"}], [None, {"metadata": None}], [{}])
    assert f["coupon_attempts_per_session"] == 0 and f["distinct_accounts_same_device"] == 1


def test_device_and_phone_come_from_session_events_when_the_request_lacks_them():
    store = FakeStore()
    store.session_rows = [row("CHECKOUT", 5, device_id="dev-X", phone_hash="ph-X", session_id="s")]
    seen = {}
    store.get_device_events = lambda d: seen.setdefault("device", d) and []
    store.get_phone_events = lambda p: seen.setdefault("phone", p) and []
    pipeline.collect_inputs({"order_id": 1, "user_id": 7, "session_id": "s", "payment_method": "CARD"}, store, 1)
    assert seen == {"device": "dev-X", "phone": "ph-X"}


def test_cod_review_needs_a_user_and_skips_history_for_card():
    store = FakeStore()
    try:
        pipeline.collect_inputs({"order_id": 1, "payment_method": "COD"}, store, 1)
        assert False, "must raise"
    except ValueError:
        pass
    out = pipeline.collect_inputs({"order_id": 1, "user_id": 7, "payment_method": "CARD"}, store, 1)
    assert out["history"] == {"total": 0, "bad": 0} and "get_cod_history" not in store.calls
    store.cod = {"total": 5, "bad": 3}
    out = pipeline.collect_inputs({"order_id": 1, "user_id": 7, "payment_method": "COD", "coupons_applied": ["CAKE10"]}, store, 1)
    assert out["profile"]["cod_bad_orders"] == 3 and out["coupon_count"] == 0 and store.calls["get_coupon_review_count"] == 1


# ---------- db.py with the HTTP layer mocked ----------
class Http:
    """Replaces db._request and records the calls."""
    def __init__(self, result=None):
        self.calls, self.result = [], result if result is not None else []

    def __call__(self, table, method="post", params=None, payload=None, headers=None):
        self.calls.append({"table": table, "method": method, "params": params, "payload": payload, "headers": headers})
        return self.result(table, method, params) if callable(self.result) else self.result


def test_update_order_patches_by_id_and_fails_when_no_row_changed():
    http = Http([{"id": 5}])
    with Patch(db, _request=http):
        db.update_order(5, {"status": "HELD"})
    assert http.calls[0] == {"table": "orders", "method": "patch", "params": {"id": "eq.5"}, "payload": {"status": "HELD"}, "headers": None}
    with Patch(db, _request=Http([])):
        try:
            db.update_order(5, {"status": "HELD"})
            assert False, "must raise"
        except RuntimeError:
            pass


def test_restriction_event_and_item_queries():
    http = Http([{"event_id": "e1"}])
    with Patch(db, _request=http):
        db.insert_restriction(7, "rate_limit", 30, "r" * 500)
        db.insert_event("BROWSE", 7, {"session_id": "s"})
        db.get_order_items(5)
        db.get_session_events("sess-1")
        db.get_device_events("dev-1")
        db.get_phone_events("ph-1")
        db.get_cod_history(7, 99)
        db.get_coupon_review_count("7")
        db.get_used_coupons(7)
    restriction, event, items, session, device, phone, cod, coupons, used = http.calls
    until = datetime.fromisoformat(restriction["payload"]["until"])
    assert restriction["table"] == "account_restrictions" and restriction["payload"]["user_id"] == 7
    assert restriction["payload"]["type"] == "rate_limit" and len(restriction["payload"]["reason"]) == 300
    assert timedelta(minutes=29) < until - datetime.now(timezone.utc) <= timedelta(minutes=30)
    assert event["table"] == "transaction_events" and event["payload"]["event_type"] == "BROWSE" and event["payload"]["event_id"]
    assert items["params"]["order_id"] == "eq.5" and items["table"] == "order_items"
    assert session["params"]["metadata->>session_id"] == "eq.sess-1" and "created_at" in session["params"]
    assert device["params"]["metadata->>device_id"] == "eq.dev-1" and phone["params"]["metadata->>phone_hash"] == "eq.ph-1"
    assert cod["params"]["id"] == "neq.99" and cod["params"]["payment_method"] == "eq.COD"
    assert coupons["params"]["event_type"] == "eq.RULELOCK_REVIEW" and coupons["params"]["metadata->>account_id"] == "eq.7"
    assert used["table"] == "coupons_used" and used["params"]["user_id"] == "eq.7"
    assert db.get_used_coupons(None) == []


def test_cod_history_counts_only_customer_caused_bad_orders():
    rows = [{"id": 1, "status": "CANCELLED", "cancelled_by": "ADMIN"}, {"id": 2, "status": "REFUSED", "cancelled_by": None},
            {"id": 3, "status": "CANCELLED", "cancelled_by": "CUSTOMER"}, {"id": 4, "status": "COMPLETED", "cancelled_by": None}]
    with Patch(db, _request=Http(rows)):
        assert db.get_cod_history(9, 10) == {"total": 4, "bad": 2}


def test_catalog_and_coupon_shapes():
    def result(table, method, params):
        if table == "products":
            return [{"id": 12, "name": "Choc", "base_price": "3500", "sizes": None}]
        return [{"code": "cake20", "percent": 20}]
    with Patch(db, _request=Http(result)):
        assert db.get_catalog() == {"sku-12": {"name": "Choc", "price": 3500.0, "sizes": None}}
        assert db.get_coupon_percents() == {"CAKE20": 20.0}


def test_review_record_goes_through_the_atomic_rpc_and_audit_inserts_ignore_duplicates():
    http = Http([])
    with Patch(db, _request=http):
        db.insert_review_record({"event_id": "e"}, {"event_id": "e"})
        db.insert_audit_row({"event_id": "e"})
    assert http.calls[0]["table"] == "rpc/record_rulelock_review" and http.calls[0]["payload"] == {"p_event": {"event_id": "e"}, "p_audit": {"event_id": "e"}}
    assert http.calls[1]["params"] == {"on_conflict": "event_id"} and "ignore-duplicates" in http.calls[1]["headers"]["Prefer"]


def test_missing_supabase_settings_raise_clear_errors():
    import config
    with Patch(config, SUPABASE_URL="", SUPABASE_SECRET_KEY=""):
        try:
            db.check_supabase()
            assert False, "must raise"
        except RuntimeError as exc:
            assert "SUPABASE_URL" in str(exc)


# ---------- c4 adapter ----------
def test_adapter_gives_c4_its_db_interface():
    store = FakeStore()
    store.add_order(5)
    a = adapter.StoreEnforcementDb(store)
    a.update_order(5, {"status": "HELD"})
    a.insert_restriction(7, "rate_limit", 30, "why")
    a.insert_audit({"event_id": "x"})
    assert store.orders[5]["status"] == "HELD" and store.restrictions[0]["minutes"] == 30 and store.audit_rows == [{"event_id": "x"}]
    assert a.get_catalog() == store.catalog and a.get_order_items(5) == store.items[5]
