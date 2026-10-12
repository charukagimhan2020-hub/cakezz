"""c4 tests with a fake db. Plain asserts, no fixtures: run with `pytest` from this folder."""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import actions
import audit
import decision
from decision import RULE_ACTION_MAP, decide

CATALOG = {"sku-1": {"name": "Choc cake", "price": 3500}, "sku-2": {"name": "Cupcakes", "price": 1200}}


class FakeDb:
    """Same interface c1 passes in. `fail` = names of methods that must raise."""
    def __init__(self, items=None, catalog=None, fail=()):
        self.items = [{"product_id": 1, "quantity": 2, "unit_price": 3500}] if items is None else items
        self.catalog = CATALOG if catalog is None else catalog
        self.fail = set(fail)
        self.order = {"status": "PENDING", "subtotal": 7000, "discount_value": 5600, "total": 1400,
                      "coupons_applied": ["CAKE50", "CAKE20", "CAKE10"]}
        self.updates, self.restrictions, self.audit_rows = [], [], []

    def _maybe_fail(self, name):
        if name in self.fail:
            raise RuntimeError(f"{name} database error")

    def update_order(self, order_id, fields):
        self._maybe_fail("update_order")
        self.updates.append((order_id, dict(fields)))
        self.order.update(fields)

    def get_order_items(self, order_id):
        self._maybe_fail("get_order_items")
        return self.items

    def get_catalog(self):
        self._maybe_fail("get_catalog")
        return self.catalog

    def insert_restriction(self, user_id, type, minutes, reason):
        self._maybe_fail("insert_restriction")
        self.restrictions.append({"user_id": user_id, "type": type, "minutes": minutes, "reason": reason})

    def insert_audit(self, payload):
        self._maybe_fail("insert_audit")
        self.audit_rows.append(payload)


class env:
    def __init__(self, **kw):
        self.kw, self.old = kw, {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = str(v)

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def run(result, db, order_id=5, account_id="7", method=None):
    return actions.apply_enforcement(result, order_id, account_id, db, method)


# ---------- decide: policy ----------
def test_rule_action_map_matches_the_contract_and_c2():
    assert RULE_ACTION_MAP["total_mismatch"] == "reject"
    assert RULE_ACTION_MAP["coupon_velocity"] == "void_discount"
    assert RULE_ACTION_MAP["quantity_ceiling"] == "reject"
    assert RULE_ACTION_MAP["price_mismatch"] == "reject"
    assert RULE_ACTION_MAP["cod_abuse"] == "hold" and RULE_ACTION_MAP["cod_abuse_severe"] == "reject"
    path = os.path.join(HERE, "..", "..", "c2-rule-engine", "rules.py")
    if os.path.exists(path):                                   # c4 and c2 must agree on every code
        spec = importlib.util.spec_from_file_location("c2_rules_for_test", path)
        c2 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(c2)
        assert c2.RULE_ACTION == RULE_ACTION_MAP


def test_every_failed_rule_maps_to_its_decision():
    for code, expected in RULE_ACTION_MAP.items():
        r = decide(1, "7", False, "failed", 0.5, "CARD", code)
        assert r["decision"] == expected and r["rule_code"] == code, code
    assert decide(1, "7", False, "failed", 0.5, "CARD", "something_new")["decision"] == "hold"
    assert decide(1, "7", False, "failed", 0.5, "CARD")["decision"] == "hold"


def test_result_always_has_the_five_contract_keys():
    for args in [(True, "", 0.5), (True, "", -0.08), (True, "", -0.5), (False, "x", 0.5), (True, "", None)]:
        r = decide(1, "7", args[0], args[1], args[2], "CARD", "coupon_usage" if not args[0] else None)
        assert set(r) == {"decision", "reason", "rule_code", "action", "account_action"}


def test_anomaly_tiers_and_rate_limit():
    ok = decide(1, "7", True, "", 0.1, "CARD")
    assert ok["decision"] == "accept" and ok["action"] == "none" and ok["account_action"] is None
    hold = decide(1, "7", True, "", -0.08, "CARD")
    assert hold["decision"] == "hold" and hold["action"] == "hold_order" and hold["account_action"] is None
    rej = decide(1, "7", True, "", -0.3, "CARD")
    assert rej["decision"] == "reject" and rej["action"] == "reject_order"
    assert rej["account_action"] == {"type": "rate_limit", "minutes": 30}
    assert decide(1, "7", True, "", -0.06, "CARD")["decision"] == "accept"      # exactly on the threshold is not below
    assert decide(1, "7", True, "", -0.1, "CARD")["decision"] == "hold"


def test_hold_action_name_depends_on_payment_method():
    assert decide(1, "7", True, "", -0.08, "COD")["action"] == "hold_cod_order"
    assert decide(1, "7", True, "", -0.08, "cod")["action"] == "hold_cod_order"
    assert decide(1, "7", True, "", -0.08, "CARD")["action"] == "hold_order"
    assert decide(1, "7", False, "r", 0.5, "COD", "cod_abuse")["action"] == "hold_cod_order"
    assert decide(1, "7", False, "r", 0.5, "CARD", "cod_order_value")["action"] == "hold_order"
    assert decide(1, "7", False, "r", 0.5, "COD", "cod_abuse")["decision"] == "hold"        # decision name stays hold


def test_thresholds_and_rate_limit_minutes_come_from_env():
    with env(ANOMALY_HOLD_THRESHOLD="0.5", ANOMALY_REJECT_THRESHOLD="0.2", RATE_LIMIT_MINUTES="45"):
        assert decide(1, "7", True, "", 0.3, "CARD")["decision"] == "hold"
        r = decide(1, "7", True, "", 0.1, "CARD")
        assert r["decision"] == "reject" and r["account_action"] == {"type": "rate_limit", "minutes": 45}
        assert decide(1, "7", True, "", 0.9, "CARD")["decision"] == "accept"
    with env(ANOMALY_HOLD_THRESHOLD="oops", RATE_LIMIT_MINUTES="-3"):
        assert decision.thresholds() == {"hold": -0.06, "reject": -0.1, "rate_limit_minutes": 30}


def test_severity_ordering_with_several_violations():
    v = lambda *codes: [{"code": c, "reason": c} for c in codes]
    r = decide(1, "7", False, "all failed", 0, "CARD", "coupon_usage", v("coupon_usage", "cod_abuse", "quantity_ceiling"))
    assert r["decision"] == "reject" and r["rule_code"] == "quantity_ceiling"
    r = decide(1, "7", False, "all failed", 0, "CARD", "coupon_usage", v("coupon_usage", "cod_abuse"))
    assert r["decision"] == "hold" and r["rule_code"] == "cod_abuse"
    r = decide(1, "7", False, "all failed", 0, "CARD", "coupon_usage", v("coupon_usage", "discount_range"))
    assert r["decision"] == "void_discount" and r["rule_code"] == "coupon_usage"        # tie keeps c2's order
    r = decide(1, "7", False, "", 0, "CARD", None, v("coupon_usage", "total_mismatch"))
    assert r["decision"] == "reject" and r["reason"] == "total_mismatch"                 # reason falls back to the violation
    assert decide(1, "7", False, "x", 0, "CARD", "price_mismatch", [None, 5, {}])["decision"] == "reject"


def test_missing_or_bad_anomaly_score_holds_never_accepts():
    for bad in (None, "abc", float("nan"), float("inf"), True):
        r = decide(1, "7", True, "", bad, "CARD")
        assert r["decision"] == "hold", bad
    assert decide(1, "7", True, "", "0.5", "CARD")["decision"] == "accept"               # numeric string is fine


def test_payment_action_and_customer_message_helpers():
    assert decision.payment_action_for("accept") == "capture_payment"
    assert decision.payment_action_for("void_discount") == "void_discount"
    assert decision.payment_action_for("hold") == "hold_payment"
    assert decision.payment_action_for("reject") == "block_payment"
    assert decision.payment_action_for("???") == "hold_payment"
    assert decision.customer_message_for("void_discount") == "Your order continues at the full price"


# ---------- apply_enforcement: every decision path ----------
def test_accept_only_stores_decision_and_reason():
    db = FakeDb()
    out = run(decide(5, "7", True, "", 0.5, "CARD"), db)
    assert out["decision"] == "accept" and out["enforcement_error"] is None
    assert db.updates == [(5, {"rulelock_decision": "accept", "rulelock_reason": "passed all checks"})]
    assert db.order["status"] == "PENDING" and db.restrictions == []


def test_void_discount_recomputes_total_from_the_catalog_and_keeps_pending():
    db = FakeDb(items=[{"product_id": 1, "quantity": 2, "unit_price": 1}, {"product_id": 2, "quantity": 3, "unit_price": 1}])
    out = run(decide(5, "7", False, "coupons stacked", 0, "CARD", "coupon_usage"), db)
    assert out["decision"] == "void_discount" and "void_discount" in out["applied"]
    assert db.order["discount_value"] == 0
    assert db.order["total"] == 3500 * 2 + 1200 * 3 == db.order["subtotal"]              # catalog prices, not unit_price 1
    assert db.order["status"] == "PENDING" and db.order["coupons_applied"] == []
    assert db.order["rulelock_decision"] == "void_discount" and db.order["rulelock_reason"] == "coupons stacked"


def test_hold_sets_held_for_card_and_cod():
    for method, action in (("CARD", "hold_order"), ("COD", "hold_cod_order")):
        db = FakeDb()
        out = run(decide(5, "7", False, "cod risk", 0, method, "cod_abuse"), db, method=method)
        assert out["decision"] == "hold" and out["action"] == action and action in out["applied"]
        assert db.order["status"] == "HELD" and db.order["rulelock_decision"] == "hold"
        assert db.restrictions == []


def test_reject_sets_blocked():
    db = FakeDb()
    out = run(decide(5, "7", False, "bad quantity", 0, "CARD", "quantity_ceiling"), db)
    assert out["decision"] == "reject" and db.order["status"] == "BLOCKED"
    assert db.order["rulelock_decision"] == "reject" and db.order["rulelock_reason"] == "bad quantity"
    assert db.restrictions == []                                                          # rule rejects do not rate-limit


def test_anomaly_reject_creates_the_rate_limit_row():
    db = FakeDb()
    out = run(decide(5, "7", True, "", -0.3, "CARD"), db, account_id="7")
    assert out["decision"] == "reject" and out["applied"] == ["reject_order", "rate_limit_account"]
    assert db.order["status"] == "BLOCKED"
    assert db.restrictions == [{"user_id": 7, "type": "rate_limit", "minutes": 30, "reason": "anomaly score indicates elevated risk"}]
    db2 = FakeDb()
    run(decide(5, 12, True, "", -0.3, "CARD"), db2, account_id=12)
    assert db2.restrictions[0]["user_id"] == 12


def test_decision_and_reason_are_always_stored():
    for result in (decide(5, "7", True, "", 0.5, "CARD"), decide(5, "7", False, "r", 0, "CARD", "coupon_usage"),
                   decide(5, "7", False, "r", 0, "COD", "cod_abuse"), decide(5, "7", False, "r", 0, "CARD", "total_mismatch")):
        db = FakeDb()
        run(result, db)
        assert db.order["rulelock_decision"] == result["decision"] and db.order["rulelock_reason"] == result["reason"]


# ---------- apply_enforcement: failures become hold ----------
def test_database_failure_becomes_hold_never_accept():
    for result in (decide(5, "7", True, "", 0.5, "CARD"),            # would be accept
                   decide(5, "7", False, "r", 0, "CARD", "coupon_usage"),
                   decide(5, "7", False, "r", 0, "CARD", "quantity_ceiling")):
        db = FakeDb(fail={"update_order"})
        out = run(result, db)
        assert out["decision"] == "hold" and out["action"] == "hold_order"
        assert out["enforcement_error"] and "held for safety" in out["reason"] and out["applied"] == []
        assert out["account_action"] is None


def test_failed_void_discount_steps_become_hold():
    for fail in ({"get_catalog"}, {"get_order_items"}):
        db = FakeDb(fail=fail)
        out = run(decide(5, "7", False, "r", 0, "CARD", "coupon_usage"), db)
        assert out["decision"] == "hold" and db.order["status"] == "HELD"             # best-effort HELD write worked
        assert db.order["discount_value"] == 5600                                     # discount was NOT voided


def test_void_discount_with_unusable_catalog_or_items_becomes_hold():
    for db in (FakeDb(items=[]), FakeDb(catalog={}), FakeDb(items=[{"product_id": 9, "quantity": 1}]),
               FakeDb(items=[{"product_id": 1, "quantity": "x"}]), FakeDb(catalog={"sku-1": {"name": "a"}})):
        out = run(decide(5, "7", False, "r", 0, "CARD", "coupon_usage"), db)
        assert out["decision"] == "hold", db.items


def test_cod_failure_keeps_the_cod_hold_action():
    out = run(decide(5, "7", False, "r", 0, "COD", "cod_abuse"), FakeDb(fail={"update_order"}), method="COD")
    assert out["decision"] == "hold" and out["action"] == "hold_cod_order"


def test_unknown_decision_becomes_hold():
    db = FakeDb()
    out = run({"decision": "banana", "reason": "?"}, db)
    assert out["decision"] == "hold" and db.order["status"] == "HELD"
    assert run({}, FakeDb())["decision"] == "hold" and run(None, FakeDb())["decision"] == "hold"


def test_rate_limit_failure_keeps_reject_because_the_order_is_already_blocked():
    for kwargs in ({"fail": {"insert_restriction"}}, {}):
        db = FakeDb(**kwargs)
        out = run(decide(5, "7", True, "", -0.3, "CARD"), db, account_id="7" if kwargs else None)
        assert out["decision"] == "reject" and db.order["status"] == "BLOCKED"
        assert out["enforcement_error"] and "rate limit could not be saved" in out["reason"]
        assert db.restrictions == []


# ---------- audit ----------
def test_audit_payload_is_minimal_and_matches_the_table_columns():
    result = decide(5, "7", False, "Quantity 9999 is outside 1 to 20", 0, "CARD", "quantity_ceiling")
    p = audit.build_audit_payload(result, 5, 7, "CARD", 34965000, "CZ-20261011120000", None)
    assert tuple(p) == audit.COLUMNS
    assert p["action"] == "REJECT" and p["decision"] == "reject" and p["rule_code"] == "quantity_ceiling"
    assert p["order_id"] == 5 and p["account_id"] == "7" and p["total"] == 34965000.0 and p["anomaly_score"] is None
    assert p["event_type"] == "RULELOCK_REVIEW" and p["event_id"] and p["created_at"]
    banned = ("name", "phone", "address", "email", "request", "payload", "items", "password")
    assert not [k for k in p if any(b in k for b in banned)]


def test_audit_action_labels_and_limits():
    for d, label in (("accept", "PASS"), ("void_discount", "VOID"), ("hold", "HOLD"), ("reject", "REJECT")):
        assert audit.build_audit_payload({"decision": d, "reason": "r"}, 1)["action"] == label
    p = audit.build_audit_payload({"decision": "hold", "reason": "x" * 5000}, "12", order_reference="r" * 500,
                                  total=float("nan"), anomaly_score="bad", payment_method="COD" * 50)
    assert len(p["reason"]) == 1000 and len(p["order_reference"]) == 200 and len(p["payment_method"]) == 40
    assert p["total"] is None and p["anomaly_score"] is None and p["order_id"] == 12
    sim = audit.build_audit_payload({"decision": "accept"}, 1, event_type="RULELOCK_SIMULATION")
    assert sim["event_type"] == "RULELOCK_SIMULATION"
    for bad in ({"event_type": "OTHER"}, {"order_id": "abc"}):
        try:
            audit.build_audit_payload({"decision": "accept"}, **({"order_id": 1} | bad) if "event_type" in bad else {"order_id": bad["order_id"]})
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_audit_record_is_insert_only():
    db = FakeDb()
    p = audit.build_audit_payload({"decision": "accept", "reason": "ok"}, 1)
    assert audit.record(db, p) == p and db.audit_rows == [p]
    assert not [n for n in dir(audit) if n.startswith(("update", "delete", "remove", "edit"))]
    try:
        audit.record(FakeDb(fail={"insert_audit"}), p)
        assert False, "expected the insert error to reach c1"
    except RuntimeError:
        pass


# ---------- optional service ----------
def test_flask_service_is_decision_only():
    import app
    c = app.app.test_client()
    assert c.get("/health").status_code == 200
    r = c.post("/enforce", json={"order_id": 5, "account_id": 7, "rule_passed": True, "anomaly_score": -0.3,
                                  "payment_method": "CARD", "total": 100, "order_reference": "CZ-1"}).get_json()
    assert r["result"]["decision"] == "reject" and r["result"]["payment_action"] == "block_payment"
    assert r["written"] is False and r["audit_preview"]["event_type"] == "RULELOCK_SIMULATION"
    assert c.post("/enforce", data="x").status_code == 400
    assert c.post("/enforce", json={"nothing": 1}).status_code == 400
    assert c.post("/enforce", json={"order_id": "abc"}).status_code == 400
