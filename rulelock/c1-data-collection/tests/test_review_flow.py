"""POST /review-order: the four decisions, raw values, idempotency, simulation, step failures.
Real c2, c3 and c4; the database is an in-memory fake."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from c1_helpers import AUTH, FakeStore, Patch, Setup, burst_rows, clean_order
import pipeline

PIPELINE_KEYS = {"c1_data_collection", "c2_rule_engine", "c3_anomaly", "c4_enforcement"}
PASS = {"passed": True, "failures": [], "violations": [], "checks": [], "rule_code": None}


def run(body, store=None):
    store = store or FakeStore()
    if body.get("simulation") is not True and body.get("order_id") not in store.orders:
        store.add_order(body["order_id"])
    with Setup(store) as client:
        return client.post("/review-order", json=body, headers=AUTH).get_json(), store


def codes(resp):
    return [v["code"] for v in resp["pipeline"]["c2_rule_engine"]["violations"]]


# ---------- the four decisions ----------
def test_accept_follows_the_contract_exactly():
    r, store = run(clean_order())
    assert r["decision"] == "accept" and r["payment_action"] == "capture_payment" and r["account_action"] is None
    assert set(r) == {"order_id", "order_reference", "decision", "reason", "customer_message", "payment_action",
                      "account_action", "pipeline", "rulelock_enabled"}
    assert r["order_id"] == 101 and r["order_reference"] == "CZ-2026101" and r["rulelock_enabled"] is True
    p = r["pipeline"]
    assert set(p) == PIPELINE_KEYS
    assert set(p["c1_data_collection"]) == {"status", "events_in_session", "session_features", "account"}
    assert set(p["c1_data_collection"]["session_features"]) == {
        "coupon_attempts_per_session", "avg_seconds_between_requests", "distinct_accounts_same_device", "distinct_addresses_same_phone"}
    assert p["c2_rule_engine"]["status"] == "pass" and p["c2_rule_engine"]["violations"] == []
    assert set(p["c2_rule_engine"]["checks"][0]) == {"code", "label", "passed", "detail"}
    assert set(p["c3_anomaly"]) == {"status", "score", "hold_threshold", "reject_threshold"}
    assert p["c3_anomaly"]["status"] == "normal"
    assert set(p["c4_enforcement"]) == {"decision", "action", "reason", "account_action"}
    assert store.orders[101]["rulelock_decision"] == "accept" and store.orders[101]["status"] == "PENDING"
    assert store.audit_rows[0]["action"] == "PASS" and ("RULELOCK_REVIEW", 101) in store.reviews


def test_review_stores_the_order_context():
    r, store = run(clean_order(coupons_applied=["CAKE10"], subtotal=7000, discount_value=700, total=6300))
    meta = store.reviews[("RULELOCK_REVIEW", 101)]["metadata"]
    for key in ("order_reference", "customer_name", "total", "payment_method", "coupons_applied", "session_id"):
        assert key in meta
    assert meta["customer_name"] == "kamal" and meta["total"] == 6300 and meta["payment_method"] == "CARD"
    assert meta["coupons_applied"] == ["CAKE10"] and meta["session_id"] == "sess-1" and meta["pipeline"] == r["pipeline"]
    assert "phone_hash" not in meta and "address_hash" not in meta           # no contact data in the stored review
    assert set(store.audit_rows[0]) == {"event_id", "event_type", "order_id", "created_at", "action", "decision", "reason",
                                        "order_reference", "account_id", "payment_method", "total", "rule_code", "anomaly_score"}


def test_void_discount_recomputes_the_order_total_from_the_catalog():
    r, store = run(clean_order(coupons_applied=["CAKE50", "CAKE20", "CAKE10"], subtotal=7000, discount_value=5600, total=1400))
    assert r["decision"] == "void_discount" and r["payment_action"] == "void_discount"
    assert r["customer_message"] == "Your order continues at the full price"
    assert "coupon_usage" in codes(r)
    order = store.orders[101]
    assert order["discount_value"] == 0 and order["total"] == 7000 and order["subtotal"] == 7000 and order["status"] == "PENDING"
    assert store.restrictions == []


def test_reusing_an_already_used_coupon_is_voided():
    store = FakeStore()
    store.used_coupons = ["CAKE10"]
    r, store = run(clean_order(coupons_applied=["CAKE10"], subtotal=7000, discount_value=700, total=6300), store)
    assert r["decision"] == "void_discount" and codes(r) == ["coupon_usage"]
    assert "already used" in r["pipeline"]["c2_rule_engine"]["violations"][0]["reason"]
    assert store.orders[101]["discount_value"] == 0 and store.orders[101]["total"] == 7000
    fresh, _ = run(clean_order(102, coupons_applied=["CAKE20"], subtotal=7000, discount_value=1400, total=5600), store)
    assert fresh["decision"] == "accept"                                       # a coupon not used before is fine


def test_hold_for_unverified_cod_over_the_cap():
    store = FakeStore()
    store.profile["completed_orders"] = 0
    r, store = run(clean_order(payment_method="COD", items=[{"sku": "sku-1", "quantity": 5, "unit_price": 3500}],
                               subtotal=17500, total=17500), store)
    assert r["decision"] == "hold" and r["payment_action"] == "hold_payment"
    assert codes(r) == ["cod_order_value"] and r["pipeline"]["c4_enforcement"]["action"] == "hold_cod_order"
    assert store.orders[101]["status"] == "HELD" and store.audit_rows[0]["action"] == "HOLD"


def test_cod_abuse_history_holds_then_rejects():
    store = FakeStore()
    store.cod = {"total": 4, "bad": 2}
    r, store = run(clean_order(101, payment_method="COD"), store)
    assert r["decision"] == "hold" and codes(r) == ["cod_abuse"]
    store.cod = {"total": 4, "bad": 3}
    store.add_order(102)
    r2, store = run(clean_order(102, payment_method="COD"), store)
    assert r2["decision"] == "reject" and codes(r2) == ["cod_abuse_severe"] and store.orders[102]["status"] == "BLOCKED"
    assert r2["pipeline"]["c1_data_collection"]["account"]["cod_bad_orders"] == 3


def test_reject_for_price_tampering_and_tampered_total():
    r, store = run(clean_order(items=[{"sku": "sku-1", "quantity": 2, "unit_price": 100}], subtotal=200, total=200))
    assert r["decision"] == "reject" and r["payment_action"] == "block_payment" and "price_mismatch" in codes(r)
    assert store.orders[101]["status"] == "BLOCKED" and store.orders[101]["rulelock_decision"] == "reject"
    assert store.restrictions == []                                          # rule rejects are not rate limited
    r2, _ = run(clean_order(102, total=1))
    assert r2["decision"] == "reject" and codes(r2) == ["total_mismatch"]
    r3, _ = run(clean_order(103, items=[{"sku": "sku-1", "quantity": 9999, "unit_price": 3500}], subtotal=34965000, total=34965000))
    assert r3["decision"] == "reject" and "quantity_ceiling" in codes(r3)


def test_anomaly_reject_adds_a_rate_limit():
    store = FakeStore()
    store.session_rows = burst_rows(8, 1.0)
    store.device_rows = [{"event_type": "LOGIN", "user_id": u, "metadata": {"device_id": "dev-1"}} for u in (7, 8, 9, 10)]
    store.phone_rows = [{"event_type": "CHECKOUT", "user_id": 7, "metadata": {"address_hash": f"a{i}"}} for i in range(4)]
    r, store = run(clean_order(), store)
    feats = r["pipeline"]["c1_data_collection"]["session_features"]
    assert feats["coupon_attempts_per_session"] == 8 and feats["distinct_accounts_same_device"] == 4
    assert feats["distinct_addresses_same_phone"] == 4 and r["pipeline"]["c1_data_collection"]["events_in_session"] == 8
    assert r["pipeline"]["c3_anomaly"]["status"] == "high_risk"
    assert r["decision"] == "reject" and r["account_action"] == {"type": "rate_limit", "minutes": 30}
    assert store.orders[101]["status"] == "BLOCKED"
    assert store.restrictions == [dict(store.restrictions[0], user_id=7, type="rate_limit", minutes=30)]


# ---------- browser values reach c2 untouched ----------
def test_c2_sees_the_raw_browser_values_plus_our_account_fields():
    seen = []
    with Patch(pipeline, validate_transaction=lambda payload, **kw: seen.append((payload, kw)) or dict(PASS)):
        r, store = run(clean_order(total=1, discount_value=999, items=[{"sku": "sku-1", "quantity": -4, "unit_price": 1}]))
    payload, kw = seen[0]
    assert payload["total"] == 1 and payload["discount_value"] == 999 and payload["items"] == [{"sku": "sku-1", "quantity": -4, "unit_price": 1}]
    assert payload["account_verified"] is True and payload["past_orders"] == 0 and payload["past_refusals"] == 0
    assert payload["used_coupons"] == []
    assert kw["catalog"]["sku-1"]["price"] == 3500.0 and kw["coupon_percents"]["CAKE20"] == 20.0
    assert store.reviews[("RULELOCK_REVIEW", 101)]["metadata"]["total"] == 1            # stored as submitted
    forged = clean_order(102, account_verified=True, past_orders=99, past_refusals=99)
    with Patch(pipeline, validate_transaction=lambda payload, **kw: seen.append((payload, kw)) or dict(PASS)):
        run(forged, FakeStore())
    assert seen[-1][0]["past_orders"] == 0 and seen[-1][0]["past_refusals"] == 0           # the body cannot forge history


# ---------- idempotency ----------
def test_second_call_returns_the_stored_review_and_changes_nothing():
    store = FakeStore()
    store.session_rows = burst_rows(8, 1.0)
    store.device_rows = [{"event_type": "LOGIN", "user_id": u, "metadata": {}} for u in (7, 8, 9, 10)]
    store.phone_rows = [{"event_type": "CHECKOUT", "user_id": 7, "metadata": {"address_hash": f"a{i}"}} for i in range(4)]
    store.add_order(101)
    calls = []
    original = pipeline.validate_transaction
    with Patch(pipeline, validate_transaction=lambda *a, **k: calls.append(1) or original(*a, **k)):
        with Setup(store) as client:
            first = client.post("/review-order", json=clean_order(), headers=AUTH).get_json()
            second = client.post("/review-order", json=clean_order(total=1), headers=AUTH).get_json()
    assert first == second and first["decision"] == "reject"
    assert len(calls) == 1 and len(store.reviews) == 1 and len(store.restrictions) == 1
    assert store.calls["update_order"] == 1 and store.calls["insert_review_record"] == 1


def test_retry_repairs_a_missing_audit_row():
    store = FakeStore()
    store.add_order(101)
    with Setup(store) as client:
        client.post("/review-order", json=clean_order(), headers=AUTH)
        store.audit_rows.clear()
        again = client.post("/review-order", json=clean_order(), headers=AUTH).get_json()
    assert again["decision"] == "accept" and len(store.audit_rows) == 1
    assert store.audit_rows[0]["event_id"] == store.reviews[("RULELOCK_REVIEW", 101)]["event_id"]


# ---------- simulation ----------
def test_simulation_writes_nothing_to_orders_and_uses_its_own_event_type():
    store = FakeStore()
    r, store = run(clean_order(9001, payment_method="COD", simulation=True,
                               simulated_account={"cod_orders": 4, "cod_bad": 3, "completed_orders": 1}), store)
    assert r["decision"] == "reject" and r["order_reference"] == "SIM-9001"
    assert ("RULELOCK_SIMULATION", 9001) in store.reviews and ("RULELOCK_REVIEW", 9001) not in store.reviews
    assert store.orders == {} and store.restrictions == [] and "update_order" not in store.calls
    assert store.calls.get("get_cod_history", 0) == 0


# ---------- a failing step becomes hold, never accept ----------
def _held(store=None, patches=(), body=None):
    store = store or FakeStore()
    stack = [p.__enter__() for p in patches]
    try:
        r, store = run(body or clean_order(), store)
    finally:
        for p in reversed(stack):
            p.__exit__(None, None, None)
    return r, store


def test_c1_failure_holds_and_marks_the_step():
    store = FakeStore()
    store.fail = {"get_catalog"}
    r, store = run(clean_order(), store)
    assert r["decision"] == "hold" and r["payment_action"] == "hold_payment"
    p = r["pipeline"]
    assert p["c1_data_collection"]["status"] == "error" and "get_catalog" in p["c1_data_collection"]["error"]
    assert p["c2_rule_engine"]["status"] == "skipped" and p["c3_anomaly"]["status"] == "skipped"
    assert store.orders[101]["status"] == "HELD"


def test_c2_failure_holds():
    def boom(*a, **k):
        raise RuntimeError("rules exploded")
    r, store = _held(patches=[Patch(pipeline, validate_transaction=boom)])
    assert r["decision"] == "hold" and r["pipeline"]["c2_rule_engine"]["status"] == "error"
    assert "rules exploded" in r["pipeline"]["c2_rule_engine"]["error"] and store.orders[101]["status"] == "HELD"


def test_c3_failure_holds():
    saved = os.environ["MODEL_PATH"]
    os.environ["MODEL_PATH"] = saved + ".missing"
    try:
        r, store = run(clean_order())
    finally:
        os.environ["MODEL_PATH"] = saved
    assert r["decision"] == "hold" and r["pipeline"]["c3_anomaly"]["status"] == "error"
    assert "not found" in r["pipeline"]["c3_anomaly"]["error"] and store.orders[101]["status"] == "HELD"


def test_c3_failure_never_downgrades_a_rule_reject_and_never_accepts_a_void():
    saved = os.environ["MODEL_PATH"]
    os.environ["MODEL_PATH"] = saved + ".missing"
    try:
        r, _ = run(clean_order(total=1))
        v, _ = run(clean_order(102, coupons_applied=["CAKE50", "CAKE20", "CAKE10"], subtotal=7000, discount_value=5600, total=1400))
    finally:
        os.environ["MODEL_PATH"] = saved
    assert r["decision"] == "reject" and v["decision"] == "hold"


def test_c4_decide_failure_holds():
    def boom(*a, **k):
        raise RuntimeError("decide exploded")
    r, store = _held(patches=[Patch(pipeline, decide=boom)])
    assert r["decision"] == "hold" and "decide exploded" in r["pipeline"]["c4_enforcement"]["error"]


def test_enforcement_database_failure_holds():
    store = FakeStore()
    store.add_order(101)
    store.fail = {"update_order"}
    r, store = run(clean_order(), store)
    assert r["decision"] == "hold" and r["payment_action"] == "hold_payment"
    assert "held for safety" in r["reason"] and r["pipeline"]["c4_enforcement"].get("error")


def test_unknown_order_makes_enforcement_fail_and_hold():
    store = FakeStore()                              # order 555 does not exist in the fake database
    with Setup(store) as client:
        r = client.post("/review-order", json=clean_order(555), headers=AUTH).get_json()
    assert r["decision"] == "hold"


def test_storage_failure_returns_a_controlled_hold_but_keeps_a_reject():
    store = FakeStore()
    store.fail = {"insert_review_record"}
    r, store = run(clean_order(), store)
    assert r["decision"] == "hold" and "could not be stored" in r["reason"] and set(r["pipeline"]) == PIPELINE_KEYS
    store2 = FakeStore()
    store2.fail = {"insert_review_record"}
    r2, _ = run(clean_order(102, total=1), store2)
    assert r2["decision"] == "reject"
    store3 = FakeStore()
    store3.fail = {"get_review_event"}
    with Setup(store3) as client:
        r3 = client.post("/review-order", json=clean_order(), headers=AUTH).get_json()
    assert r3["decision"] == "hold" and r3["reason"] == "Review storage is temporarily unavailable"


def test_pipeline_crash_is_a_hold_too():
    def boom(*a, **k):
        raise RuntimeError("orchestrator exploded")
    r, store = _held(patches=[Patch(pipeline, run_review=boom)])
    assert r["decision"] == "hold" and set(r["pipeline"]) == PIPELINE_KEYS


# ---------- bad requests ----------
def test_bad_review_requests():
    with Setup(FakeStore()) as client:
        assert client.post("/review-order", json={}, headers=AUTH).status_code == 400
        assert client.post("/review-order", json={"order_id": "abc"}, headers=AUTH).status_code == 400
        assert client.post("/review-order", json={"order_id": 1.5}, headers=AUTH).status_code == 400
        assert client.post("/review-order", data="not json", headers=AUTH).status_code == 400
        assert client.post("/review-order", json=[1, 2], headers=AUTH).status_code == 400
        too_big = client.post("/review-order", data=b"x" * 70000, headers=AUTH, content_type="application/json")
        assert too_big.status_code == 413 and too_big.get_json()["error"]
