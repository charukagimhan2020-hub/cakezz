"""c2 tests. Plain asserts, no fixtures: run with `pytest` from this folder."""
import importlib
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import rules
from rules import validate_transaction as validate

CATALOG = {"sku-1": {"name": "Choc cake", "price": 3500}, "sku-2": {"name": "Cupcakes", "price": 1200},
           "sku-3": {"name": "Cookie", "price": 100}}


def order(**over):
    """An honest order: 2 x sku-1, no coupon, card."""
    base = {"order_id": 1, "order_reference": "CZ-1", "user_id": 7, "payment_method": "CARD",
            "items": [{"sku": "sku-1", "quantity": 2, "unit_price": 3500}],
            "coupons_applied": [], "subtotal": 7000, "discount_value": 0, "total": 7000,
            "account_verified": True, "past_orders": 0, "past_refusals": 0}
    base.update(over)
    return base


def run(payload, **kw):
    kw.setdefault("catalog", CATALOG)
    return validate(payload, **kw)


def check(result, code):
    return [c for c in result["checks"] if c["code"] == code]


def failed_codes(result):
    return [v["code"] for v in result["violations"]]


# ---------- shape ----------
def test_honest_order_passes_and_shape_is_the_contract():
    r = run(order())
    assert set(r) == {"passed", "failures", "violations", "checks", "rule_code"}
    assert r["passed"] is True and r["failures"] == [] and r["violations"] == [] and r["rule_code"] is None
    for c in r["checks"]:
        assert set(c) == {"code", "label", "passed", "detail"}
        assert c["label"] and c["detail"]
    codes = {c["code"] for c in r["checks"]}
    assert {"coupon_usage", "discount_range", "quantity_ceiling", "minimum_purchase", "price_mismatch",
            "total_mismatch", "coupon_velocity", "cod_order_value", "cod_abuse"} <= codes


def test_no_catalog_and_no_history_are_not_applicable():
    r = validate(order(coupons_applied=["CAKE10"], subtotal=7000, discount_value=700, total=6300))
    assert r["passed"]
    for code in ("price_mismatch", "total_mismatch", "coupon_velocity"):
        assert check(r, code)[0]["passed"] and check(r, code)[0]["detail"].startswith("Not applicable")


# ---------- one pass and one fail per rule ----------
def test_coupon_usage():
    assert rules.check_coupon_usage(["CAKE20"]).passed
    assert rules.check_coupon_usage([]).passed
    bad = rules.check_coupon_usage(["CAKE50", "CAKE20"])
    assert not bad.passed and bad.code == "coupon_usage"
    assert not rules.check_coupon_usage(["FREECAKE"]).passed
    assert not rules.check_coupon_usage("CAKE10").passed


def test_discount_range():
    assert rules.check_discount_range(6000, 10000).passed
    assert not rules.check_discount_range(6001, 10000).passed
    assert not rules.check_discount_range(float("nan"), 10000).passed
    assert not rules.check_discount_range(0, float("nan")).passed
    assert not rules.check_discount_range(-5, 100).passed


def test_quantity_ceiling():
    assert rules.check_quantity_ceiling("sku-1", 1).passed
    assert rules.check_quantity_ceiling("sku-1", 20).passed
    for bad in (0, -1, 21, 9999, 2.5, "abc", None, float("nan")):
        assert not rules.check_quantity_ceiling("sku-1", bad).passed, bad


def test_minimum_purchase_only_with_a_coupon():
    assert rules.check_minimum_purchase(300, []).passed                       # no coupon: not applicable
    assert rules.check_minimum_purchase(300, ["CAKE10"]).code == "minimum_purchase"
    assert not rules.check_minimum_purchase(300, ["CAKE10"]).passed
    assert rules.check_minimum_purchase(600, ["CAKE10"]).passed
    assert not rules.check_minimum_purchase("abc", ["CAKE10"]).passed


def test_small_order_without_coupon_is_not_flagged():
    r = run(order(items=[{"sku": "sku-3", "quantity": 2, "unit_price": 100}], subtotal=200, total=200))
    assert r["passed"], r["failures"]


def test_price_mismatch_one_percent_tolerance():
    assert rules.check_price_mismatch([{"sku": "sku-1", "unit_price": 3520}], CATALOG).passed        # 0.57 %
    assert not rules.check_price_mismatch([{"sku": "sku-1", "unit_price": 3600}], CATALOG).passed   # 2.9 %
    assert not rules.check_price_mismatch([{"sku": "sku-9", "unit_price": 1}], CATALOG).passed       # not in catalog
    assert not rules.check_price_mismatch([{"sku": "sku-1"}], CATALOG).passed                        # no unit_price
    assert not rules.check_price_mismatch([{"sku": "sku-1", "unit_price": "x"}], CATALOG).passed


def test_price_mismatch_with_sizes():
    cat = {"sku-c": {"price": 1000, "sizes": {"2": 1800}}}
    assert rules.check_price_mismatch([{"sku": "sku-c", "size": "2", "unit_price": 1810}], cat).passed
    assert not rules.check_price_mismatch([{"sku": "sku-c", "size": "2", "unit_price": 1750}], cat).passed


def test_total_mismatch():
    items = [{"sku": "sku-1", "quantity": 2, "unit_price": 3500}]
    assert rules.check_total_mismatch(items, [], 7000, CATALOG).passed
    assert rules.check_total_mismatch(items, ["CAKE20"], 5600, CATALOG).passed
    assert rules.check_total_mismatch(items, ["CAKE50", "CAKE20"], 2100, CATALOG).passed   # stacked: 70 % off
    bad = rules.check_total_mismatch(items, [], 100, CATALOG)
    assert not bad.passed and bad.code == "total_mismatch"
    assert not rules.check_total_mismatch(items, [], None, CATALOG).passed
    assert not rules.check_total_mismatch(items, [], float("nan"), CATALOG).passed


def test_coupon_velocity():
    assert rules.check_coupon_velocity(["CAKE10"], 5).passed
    assert not rules.check_coupon_velocity(["CAKE10"], 6).passed
    assert rules.check_coupon_velocity([], 50).passed
    assert rules.check_coupon_velocity(["CAKE10"], None).passed
    assert not rules.check_coupon_velocity(["CAKE10"], "many").passed


def test_cod_order_value():
    assert rules.check_cod_order_value(16000, True).passed
    assert rules.check_cod_order_value(15000, False).passed
    bad = rules.check_cod_order_value(15001, False)
    assert not bad.passed and bad.code == "cod_order_value"
    assert not rules.check_cod_order_value("abc", False).passed


def test_cod_abuse():
    assert rules.check_cod_abuse(10, 1).passed
    assert rules.check_cod_abuse(0, 0).passed
    assert rules.check_cod_abuse(10, 2).passed                       # 20 % is under the 50 % ratio
    assert rules.check_cod_abuse(4, 2).code == "cod_abuse" and not rules.check_cod_abuse(4, 2).passed
    assert rules.check_cod_abuse(4, 3).code == "cod_abuse_severe"
    assert not rules.check_cod_abuse("x", 1).passed
    assert not rules.check_cod_abuse(-1, 0).passed


def test_coupon_reuse_is_a_coupon_usage_failure():
    assert rules.check_coupon_usage(["CAKE10"], None, ["CAKE20"]).passed
    bad = rules.check_coupon_usage(["CAKE10"], None, ["cake10", "CAKE20"])
    assert not bad.passed and bad.code == "coupon_usage" and "already used" in bad.reason
    assert rules.check_coupon_usage(["CAKE10"], None, None).passed and rules.check_coupon_usage(["CAKE10"], None, "junk").passed
    r = run(order(coupons_applied=["CAKE10"], discount_value=700, total=6300, used_coupons=["CAKE10"]))
    assert r["rule_code"] == "coupon_usage" and "already used" in r["failures"][0]
    ok = run(order(coupons_applied=["CAKE10"], discount_value=700, total=6300, used_coupons=["CAKE20"]))
    assert ok["passed"], ok["failures"]


# ---------- demo cases through validate_transaction ----------
def test_demo_coupon_stacking_three_coupons():
    r = run(order(coupons_applied=["CAKE50", "CAKE20", "CAKE10"], discount_value=5600, total=1400))
    assert not r["passed"]
    assert r["rule_code"] == "coupon_usage"
    assert rules.RULE_ACTION["coupon_usage"] == "void_discount"
    assert "total_mismatch" not in failed_codes(r)      # the total was recomputed with 80 % and matches


def test_demo_price_tampering():
    r = run(order(items=[{"sku": "sku-1", "quantity": 2, "unit_price": 100}], subtotal=200, total=200))
    assert r["rule_code"] == "price_mismatch"
    assert "total_mismatch" in failed_codes(r)
    assert rules.RULE_ACTION[r["rule_code"]] == "reject"


def test_demo_quantity_minus_one_and_9999():
    for q in (-1, 9999):
        r = run(order(items=[{"sku": "sku-1", "quantity": q, "unit_price": 3500}], subtotal=3500 * q, total=3500 * q))
        assert r["rule_code"] == "quantity_ceiling", q


def test_demo_unverified_cod_over_cap():
    r = run(order(payment_method="COD", items=[{"sku": "sku-1", "quantity": 5, "unit_price": 3500}],
                  subtotal=17500, total=17500, account_verified=False))
    assert r["rule_code"] == "cod_order_value" and failed_codes(r) == ["cod_order_value"]
    ok = run(order(payment_method="COD", items=[{"sku": "sku-1", "quantity": 5, "unit_price": 3500}],
                   subtotal=17500, total=17500, account_verified=True))
    assert ok["passed"]


def test_demo_cod_abuse_history():
    hold = run(order(payment_method="COD", past_orders=4, past_refusals=2))
    assert hold["rule_code"] == "cod_abuse" and rules.RULE_ACTION["cod_abuse"] == "hold"
    reject = run(order(payment_method="COD", past_orders=4, past_refusals=3))
    assert reject["rule_code"] == "cod_abuse_severe" and rules.RULE_ACTION["cod_abuse_severe"] == "reject"


def test_demo_tampered_total():
    r = run(order(total=1))
    assert r["rule_code"] == "total_mismatch" and failed_codes(r) == ["total_mismatch"]
    assert "does not match" in r["failures"][0]


def test_card_order_shows_cod_checks_as_not_applicable():
    r = run(order())
    assert check(r, "cod_abuse")[0]["detail"].startswith("Not applicable")


def test_severity_order_most_severe_first():
    r = run(order(items=[{"sku": "sku-3", "quantity": 35, "unit_price": 100}], subtotal=100, discount_value=90, total=10))
    assert r["rule_code"] == "quantity_ceiling"
    assert failed_codes(r)[0] == "quantity_ceiling"
    assert any(not c["passed"] and c["code"] == "discount_range" for c in r["checks"])
    assert any(c["passed"] for c in r["checks"])


# ---------- bad input never crashes ----------
def test_bad_input_gives_failed_checks_not_crashes():
    bad_payloads = [
        None, [], "text", 5, {},
        order(items="nope"), order(items=[None, 5, "x"]), order(items=[]),
        order(coupons_applied="CAKE10"), order(coupons_applied=[None, 5]),
        order(subtotal="abc"), order(subtotal=None), order(total="abc"), order(total=float("nan")),
        order(discount_value="abc"), order(discount_value=float("inf")),
        order(items=[{"sku": "sku-1", "quantity": "many", "unit_price": "cheap"}]),
        order(items=[{"sku": None, "quantity": -3, "unit_price": -50}]),
        order(items=[{"sku": "sku-1", "quantity": float("nan"), "unit_price": float("nan")}]),
        order(subtotal=-100, total=-100, discount_value=-5),
        order(payment_method="COD", past_orders="a", past_refusals=None, account_verified="no"),
        order(payment_method=None), order(payment_method=123),
    ]
    for p in bad_payloads:
        for kw in ({}, {"catalog": None}, {"coupon_review_count": "x"}, {"catalog": "not a dict"}):
            kw.setdefault("catalog", CATALOG)
            r = validate(p, **kw)
            assert set(r) == {"passed", "failures", "violations", "checks", "rule_code"}
            assert isinstance(r["checks"], list) and r["checks"]
    for p in [None, [], {}, order(items="nope"), order(items=[]), order(subtotal="abc"), order(total="abc"),
              order(items=[{"sku": "sku-1", "quantity": "many", "unit_price": "cheap"}])]:
        assert not run(p)["passed"], p


def test_numeric_strings_are_accepted_as_numbers():
    r = run(order(items=[{"sku": "sku-1", "quantity": "2", "unit_price": "3500"}], subtotal="7000", total="7000"))
    assert r["passed"], r["failures"]


# ---------- settings come from env vars ----------
def test_settings_are_read_from_env():
    saved = {k: os.environ.get(k) for k in ("MAX_COUPONS", "MAX_QUANTITY_PER_LINE", "MAX_DISCOUNT_RATIO", "BAD_NUMBER")}
    try:
        os.environ["MAX_COUPONS"] = "3"
        os.environ["MAX_QUANTITY_PER_LINE"] = "5"
        os.environ["MAX_DISCOUNT_RATIO"] = "not-a-number"
        importlib.reload(rules)
        assert rules.MAX_COUPONS == 3 and rules.MAX_QUANTITY_PER_LINE == 5
        assert rules.MAX_DISCOUNT_RATIO == 0.6                      # bad value falls back to the default
        assert rules.check_coupon_usage(["CAKE50", "CAKE20", "CAKE10"]).passed
        assert not rules.check_quantity_ceiling("sku-1", 6).passed
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(rules)
    assert rules.MAX_COUPONS == 1 and rules.MAX_QUANTITY_PER_LINE == 20
