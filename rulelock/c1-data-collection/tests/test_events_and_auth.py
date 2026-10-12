"""POST /events, bearer auth on every endpoint, audit APIs, toggle, info, readiness."""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from c1_helpers import AUTH, FakeStore, Patch, Setup, TOKEN, app, clean_order, config, events

appmod = sys.modules["app"]
EVENT = {"event_type": "BROWSE", "user_id": 7, "session_id": "sess-1", "device_id": "dev-1",
         "phone_hash": "ph-1", "address_hash": "ad-1", "metadata": {"page": "index"}}


def post(client, body, headers=AUTH, **kw):
    return client.post("/events", json=body, headers=headers, **kw)


# ---------- POST /events ----------
def test_event_is_stored_with_ids_inside_metadata():
    store = FakeStore()
    with Setup(store) as client:
        r = post(client, EVENT)
    assert r.status_code == 201 and r.get_json()["stored"] is True
    row = store.events[0]
    assert row["event_type"] == "BROWSE" and row["user_id"] == 7
    assert row["metadata"] == {"page": "index", "session_id": "sess-1", "device_id": "dev-1",
                               "phone_hash": "ph-1", "address_hash": "ad-1", "account_id": "7"}


def test_all_five_event_types_are_accepted_and_reserved_keys_cannot_be_overridden():
    store = FakeStore()
    with Setup(store) as client:
        for t in ("LOGIN", "BROWSE", "ADD_TO_CART", "APPLY_COUPON", "CHECKOUT"):
            assert post(client, {**EVENT, "event_type": t}).status_code == 201
        post(client, {**EVENT, "metadata": {"session_id": "evil", "device_id": "evil", "x": 1}})
        post(client, {"event_type": "BROWSE", "session_id": "anon"})                # anonymous visitor, no ids
    assert len(store.events) == 7
    assert store.events[5]["metadata"]["session_id"] == "sess-1" and store.events[5]["metadata"]["device_id"] == "dev-1"
    assert store.events[5]["metadata"]["x"] == 1
    assert store.events[6]["user_id"] is None and store.events[6]["metadata"]["phone_hash"] is None


def test_bad_events_are_rejected():
    store = FakeStore()
    with Setup(store) as client:
        assert post(client, {**EVENT, "event_type": "HACK"}).status_code == 400
        assert post(client, {**EVENT, "event_type": None}).status_code == 400
        assert post(client, {**EVENT, "event_type": "RULELOCK_REVIEW"}).status_code == 400     # review events are not shopper events
        assert post(client, {k: v for k, v in EVENT.items() if k != "session_id"}).status_code == 400
        assert post(client, {**EVENT, "session_id": 123}).status_code == 400
        assert post(client, {**EVENT, "session_id": "x" * 101}).status_code == 400
        assert post(client, {**EVENT, "user_id": "abc"}).status_code == 400
        assert post(client, {**EVENT, "metadata": [1]}).status_code == 400
        assert post(client, [EVENT]).status_code == 400
        assert client.post("/events", data="nope", headers=AUTH).status_code == 400
    assert store.events == []


def test_event_body_size_is_limited():
    store = FakeStore()
    with Setup(store) as client:
        r = post(client, {**EVENT, "metadata": {"blob": "a" * 9000}})
        assert r.status_code == 413
        assert post(client, {**EVENT, "unknown_top_level": "ignored"}).status_code == 201
    assert len(store.events) == 1 and "unknown_top_level" not in store.events[0]["metadata"]


def test_event_storage_failure_is_503_not_a_crash():
    store = FakeStore()
    store.fail = {"insert_event"}
    with Setup(store) as client:
        assert post(client, EVENT).status_code == 503


# ---------- bearer auth ----------
PROTECTED = [("POST", "/events"), ("POST", "/review-order"), ("GET", "/audit-log"), ("GET", "/audit-log/latest"),
             ("GET", "/audit-log/123"), ("GET", "/dashboard/summary"), ("GET", "/settings/rulelock"),
             ("POST", "/settings/rulelock"), ("GET", "/pipeline/info")]


def test_every_protected_endpoint_rejects_missing_or_wrong_tokens():
    with Setup(FakeStore()) as client:
        for method, path in PROTECTED:
            for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN},
                            {"Authorization": f"Basic {TOKEN}"}, {"Authorization": "Bearer "}):
                r = client.open(path, method=method, json={}, headers=headers)
                assert r.status_code == 401, (method, path, headers)


def test_right_token_works_and_health_needs_no_token():
    with Setup(FakeStore()) as client:
        assert client.get("/settings/rulelock", headers=AUTH).status_code == 200
        assert client.get("/health").status_code == 200 and client.get("/health").get_json() == {"status": "ok"}


def test_auth_fails_closed_without_a_token_unless_the_local_override_is_set():
    with Setup(FakeStore(), token=None, allow_no_auth=False) as client:
        assert client.get("/audit-log").status_code == 401
        assert client.get("/settings/rulelock", headers=AUTH).status_code == 401
    with Setup(FakeStore(), token=None, allow_no_auth=True) as client:
        assert client.get("/settings/rulelock").status_code == 200


def test_production_startup_requires_a_token():
    try:
        config.validate_auth_configuration(token=None, production=True)
        assert False, "must fail"
    except RuntimeError as exc:
        assert "RULELOCK_API_TOKEN" in str(exc)
    config.validate_auth_configuration(token=None, production=False)
    config.validate_auth_configuration(token="x", production=True)


# ---------- audit APIs ----------
def _reviewed_store():
    store = FakeStore()
    with Setup(store) as client:
        for oid in (101, 102):
            store.add_order(oid)
            client.post("/review-order", json=clean_order(oid), headers=AUTH)
    return store


def test_audit_latest_and_detail_return_the_full_pipeline():
    store = _reviewed_store()
    with Setup(store) as client:
        latest = client.get("/audit-log/latest", headers=AUTH)
        by_id = client.get("/audit-log/101", headers=AUTH)
        by_ref = client.get("/audit-log/CZ-2026101", headers=AUTH)
    assert latest.status_code == 200 and latest.get_json()["order_id"] == 102
    for r, oid in ((by_id, 101), (by_ref, 101)):
        body = r.get_json()
        assert r.status_code == 200 and body["order_id"] == oid and body["order_reference"] == "CZ-2026101"
        assert set(body["pipeline"]) == {"c1_data_collection", "c2_rule_engine", "c3_anomaly", "c4_enforcement"}
        assert body["decision"] == "accept" and body["customer_name"] == "kamal" and body["payment_method"] == "CARD"
        assert body["pipeline"]["c2_rule_engine"]["checks"]


def test_audit_detail_not_found_cases():
    store = _reviewed_store()
    with Setup(store) as client:
        assert client.get("/audit-log/999", headers=AUTH).status_code == 404
        assert client.get("/audit-log/CZ-NOPE", headers=AUTH).status_code == 404
        assert client.get("/audit-log/a%20b;drop", headers=AUTH).status_code == 404
    with Setup(FakeStore()) as client:
        r = client.get("/audit-log/latest", headers=AUTH)
        assert r.status_code == 404 and r.get_json()["error"]
    broken = FakeStore()
    broken.fail = {"get_latest_review_event"}
    with Setup(broken) as client:
        assert client.get("/audit-log/latest", headers=AUTH).status_code == 503


def test_audit_log_list_and_cursor_validation():
    store = _reviewed_store()
    with Setup(store) as client:
        r = client.get("/audit-log?limit=1", headers=AUTH).get_json()
        assert r["count"] == 1 and set(r["records"][0]) >= {"action_id", "timestamp", "action", "decision", "order_reference", "score"}
        assert client.get("/audit-log?cursor=abc", headers=AUTH).status_code == 400
        assert client.get("/audit-log?limit=zzz", headers=AUTH).status_code == 200


def test_dashboard_summary_shape():
    store = _reviewed_store()
    with Setup(store) as client:
        r = client.get("/dashboard/summary", headers=AUTH)
    body = r.get_json()
    assert r.status_code == 200 and body["enforcement_feed"] and set(body["rule_violations"]) == {"total", "coupon", "cod"}
    assert body["components"]["enforcement_engine"]["audit_log_entries"] == 2


# ---------- toggle, info, readiness ----------
def test_toggle_endpoints():
    store = FakeStore()
    with Setup(store) as client:
        assert client.get("/settings/rulelock", headers=AUTH).get_json() == {"rulelock_enabled": False, "source": "default"}
        assert client.post("/settings/rulelock", json={"rulelock_enabled": True}, headers=AUTH).get_json()["rulelock_enabled"] is True
        assert client.get("/settings/rulelock", headers=AUTH).get_json()["rulelock_enabled"] is True
        assert client.post("/settings/rulelock", json={}, headers=AUTH).status_code == 400
        store.fail = {"set_rulelock_setting"}
        assert client.post("/settings/rulelock", json={"rulelock_enabled": False}, headers=AUTH).status_code == 503


def test_pipeline_info_and_ready():
    with Setup(FakeStore()) as client:
        info = client.get("/pipeline/info", headers=AUTH).get_json()
        assert info["model"] == "IsolationForest" and info["loaded"] is True and len(info["features"]) == 4
        assert info["thresholds"]["hold"] == -0.06 and info["rule_thresholds"]["max_coupons"] == 1
        assert info["enforcement"]["rate_limit_minutes"] == 30
    with Patch(appmod, db=FakeStore()):
        r = app.test_client().get("/ready")
        assert r.status_code == 200 and r.get_json() == {"ready": True, "checks": {"model_loaded": True, "supabase_reachable": True}}
    broken = FakeStore()
    broken.fail = {"check_supabase"}
    with Patch(appmod, db=broken):
        r = app.test_client().get("/ready")
        assert r.status_code == 503 and r.get_json()["checks"]["supabase_reachable"] is False
    saved = os.environ["MODEL_PATH"]
    os.environ["MODEL_PATH"] = saved + ".missing"
    try:
        with Patch(appmod, db=FakeStore()):
            r = app.test_client().get("/ready")
            assert r.status_code == 503 and r.get_json()["checks"]["model_loaded"] is False and "model_error" in r.get_json()
    finally:
        os.environ["MODEL_PATH"] = saved


def test_unknown_routes_answer_json_and_no_foreign_defaults_remain():
    assert app.test_client().get("/nope").get_json() == {"error": "not found"}
    assert not config.CORS_ORIGINS                                     # CORS is off by default
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    for path in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        text = open(path, encoding="utf-8").read()
        for needle in ("supabase.co", "github.io", "CAKELY_ORIGINS", "idlmmvmxbdebpurovkee"):
            if os.path.basename(path) != "test_events_and_auth.py":
                assert needle not in text, (path, needle)
