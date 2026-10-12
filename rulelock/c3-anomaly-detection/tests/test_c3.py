"""c3 tests. Plain asserts, no fixtures: run with `pytest` from this folder."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

import evaluate
import features
import scoring
import synthetic_data as sd
import train_model

# Train once into a temp file and point MODEL_PATH at it (the repo never contains model.joblib).
_TMP = tempfile.mkdtemp()
_MODEL_FILE = os.path.join(_TMP, "model.joblib")
train_model.train(_MODEL_FILE)
os.environ["MODEL_PATH"] = _MODEL_FILE


def feats(row):
    return dict(zip(features.FEATURE_NAMES, row))


class env:
    """with env(NAME=value): temporarily set (or remove with None) environment variables."""
    def __init__(self, **kw):
        self.kw, self.old = kw, {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------- features ----------
def test_feature_names_are_the_four_contract_names():
    assert features.FEATURE_NAMES == ["coupon_attempts_per_session", "avg_seconds_between_requests",
                                      "distinct_accounts_same_device", "distinct_addresses_same_phone"]


def test_values_are_clipped_to_the_training_ranges():
    x = features.session_to_features(feats([9999, 0, 100, -5]))
    assert x.shape == (1, 4)
    assert x.tolist() == [[15.0, 1.0, 8.0, 1.0]]
    x = features.session_to_features(feats([-3, 99999, 1, 1000]))
    assert x.tolist() == [[0.0, 600.0, 1.0, 8.0]]


def test_missing_or_bad_input_becomes_defaults():
    assert features.session_to_features({"coupon_attempts_per_session": 2}).tolist() == [[2.0, 30.0, 1.0, 1.0]]
    default = [[0.0, 30.0, 1.0, 1.0]]
    for bad in (None, [], "text", 5, {}):
        assert features.session_to_features(bad).tolist() == default
    bad_values = feats(["abc", float("nan"), float("inf"), None])
    assert features.session_to_features(bad_values).tolist() == default
    assert features.session_to_features(feats([True, False, [1], {}])).tolist() == default


def test_average_seconds_between_requests_helper():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
    rows = [{"created_at": (now - timedelta(seconds=s)).isoformat()} for s in (40, 20, 0)]
    assert features.average_seconds_between_requests(rows, now) == 20.0
    assert features.average_seconds_between_requests(rows[:2], now) == 30            # fewer than 3 events
    old = [{"created_at": (now - timedelta(minutes=45)).isoformat()}] * 3
    assert features.average_seconds_between_requests(old, now) == 30                 # outside the 30 min window
    assert features.average_seconds_between_requests([{"created_at": "garbage"}, None, {}], now) == 30


# ---------- model ----------
def test_model_loads_and_reports_metadata():
    assert scoring.model_status()["loaded"] is True
    raw, anomaly = scoring.score_session(feats([1, 30, 1, 1]))
    assert isinstance(raw, float) and isinstance(anomaly, bool)
    assert scoring.is_model_loaded() is True
    meta = scoring.model_metadata()
    assert meta["model"] == "IsolationForest" and meta["loaded"] is True
    assert meta["features"] == features.FEATURE_NAMES
    assert set(meta["thresholds"]) == {"hold", "reject"}
    assert "synthetic" in meta["training_data"]


def test_training_uses_normal_sessions_only():
    assert not hasattr(train_model, "generate_abuse_sessions")
    normal = sd.generate_normal_sessions(5000)
    assert normal[:, 2].max() <= 2 and normal[:, 3].max() <= 2 and normal[:, 0].max() <= 5


def test_missing_model_file_does_not_break_import_and_fails_clearly():
    with env(MODEL_PATH=os.path.join(_TMP, "does-not-exist.joblib")):
        try:
            scoring.score_session(feats([1, 30, 1, 1]))
            assert False, "expected ModelNotLoadedError"
        except scoring.ModelNotLoadedError as exc:
            assert "not found" in str(exc) and "train_model.py" in str(exc)
        status = scoring.model_status()
        assert status["loaded"] is False and status["error"]
        meta = scoring.model_metadata()                                 # must not raise
        assert meta["loaded"] is False and meta["error"]
    assert scoring.model_status()["loaded"] is True


def test_corrupt_model_file_fails_clearly():
    bad = os.path.join(_TMP, "corrupt.joblib")
    open(bad, "wb").write(b"not a model")
    with env(MODEL_PATH=bad):
        try:
            scoring.score_session(feats([1, 30, 1, 1]))
            assert False, "expected ModelNotLoadedError"
        except scoring.ModelNotLoadedError as exc:
            assert "could not be loaded" in str(exc)


# ---------- normal passes, abuse is flagged ----------
def test_normal_sessions_stay_above_the_hold_threshold():
    for row in sd.generate_demo_normal(300):          # 0-2 coupons, 20-90 s, 1 account, 1 address
        raw, anomaly = scoring.score_session(feats(row))
        assert raw > -0.06 and anomaly is False, (row, raw)
    raw, anomaly = scoring.score_session(feats([1, 30, 1, 1]))
    assert raw > -0.06 and not anomaly


def test_demo_abuse_sessions_fall_below_the_hold_threshold():
    for maker in (sd.generate_coupon_stacking, sd.generate_multi_account, sd.generate_cod_address_farming):
        for row in maker(100):
            raw, anomaly = scoring.score_session(feats(row))
            assert raw < -0.06 and anomaly is True, (maker.__name__, row, raw)
    raw, anomaly = scoring.score_session(feats([8, 2, 5, 5]))
    assert anomaly and raw < -0.1


def test_abuse_scores_lower_than_normal_on_average():
    n = np.mean([scoring.score_session(feats(r))[0] for r in sd.generate_demo_normal(100)])
    a = np.mean([scoring.score_session(feats(r))[0] for r in sd.generate_abuse_sessions(99)])
    assert a < n - 0.1


def test_wild_values_are_clipped_not_crashing():
    raw, anomaly = scoring.score_session(feats([10 ** 9, -1, 10 ** 6, 10 ** 6]))
    assert anomaly is True and raw < -0.1


# ---------- thresholds from env ----------
def test_thresholds_are_read_from_env():
    assert scoring.thresholds() == {"hold": -0.06, "reject": -0.1}
    with env(ANOMALY_HOLD_THRESHOLD="0.5", ANOMALY_REJECT_THRESHOLD="0.4"):
        assert scoring.thresholds() == {"hold": 0.5, "reject": 0.4}
        assert scoring.score_session(feats([1, 30, 1, 1]))[1] is True       # every score is now below 0.5
        assert scoring.model_metadata()["thresholds"] == {"hold": 0.5, "reject": 0.4}
    with env(ANOMALY_HOLD_THRESHOLD="-5"):
        assert scoring.score_session(feats([9, 2, 5, 5]))[1] is False
    with env(ANOMALY_HOLD_THRESHOLD="not-a-number"):
        assert scoring.thresholds()["hold"] == -0.06


# ---------- evaluate and the optional service ----------
def test_evaluate_reports_full_recall_and_no_false_alarm_on_demo_normal():
    r = evaluate.run()
    assert r["pr"]["hold"]["recall"] == 1.0
    demo = [x for x in r["rows"] if x["group"] == "normal: demo definition"][0]
    assert demo["hold_pct"] == 0.0
    assert {f["name"] for f in r["fixtures"]} >= {"typical_customer", "coupon_burst"}


def test_flask_service():
    import app
    c = app.app.test_client()
    assert c.get("/health").status_code == 200
    assert c.get("/ready").status_code == 200
    ok = c.post("/score", json=feats([1, 30, 1, 1])).get_json()
    assert ok["is_anomaly"] is False and ok["hold_threshold"] == -0.06
    assert c.post("/score", json=feats([9, 2, 5, 5])).get_json()["is_anomaly"] is True
    assert c.post("/score", data="x").status_code == 400
    with env(MODEL_PATH=os.path.join(_TMP, "missing.joblib")):
        assert c.get("/ready").status_code == 503
        assert c.post("/score", json={}).status_code == 503
        assert c.get("/health").status_code == 200
