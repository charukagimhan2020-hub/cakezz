"""c3 scoring: score one session with the trained Isolation Forest.

  score_session(features) -> (raw_score, is_anomaly)    is_anomaly = raw_score < hold threshold
  model_metadata() -> dict                               never raises
  is_model_loaded() -> bool                              True once a model has been loaded
  model_status() -> {loaded, path, error}                tries to load; used by /ready

The model file is loaded lazily on the first call, so importing this module never fails when the file is missing.
A missing or unreadable file raises ModelNotLoadedError (a clear message) only when scoring is called.
Lower score = more anomalous. Thresholds come from env vars (read at call time): hold -0.06, reject -0.1.
"""
import logging
import os

import joblib
import sklearn

from features import FEATURE_NAMES, TRAINING_RANGES, session_to_features

logger = logging.getLogger(__name__)

DEFAULT_HOLD = -0.06
DEFAULT_REJECT = -0.1
_cache = {"path": None, "model": None}


class ModelNotLoadedError(RuntimeError):
    """The anomaly model file is missing or cannot be read."""


def model_path():
    return os.environ.get("MODEL_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.joblib")


def _float_env(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        logger.warning("Invalid %s; using %s", name, default)
        return float(default)


def thresholds():
    return {"hold": _float_env("ANOMALY_HOLD_THRESHOLD", DEFAULT_HOLD),
            "reject": _float_env("ANOMALY_REJECT_THRESHOLD", DEFAULT_REJECT)}


def _get_model():
    path = model_path()
    if _cache["model"] is not None and _cache["path"] == path:
        return _cache["model"]
    if not os.path.isfile(path):
        raise ModelNotLoadedError(
            f"Anomaly model file not found at {path}. Run `python train_model.py` in c3-anomaly-detection "
            "(it runs at Docker build) or set MODEL_PATH.")
    try:
        model = joblib.load(path)
    except Exception as exc:
        raise ModelNotLoadedError(f"Anomaly model file {path} could not be loaded: {exc}") from exc
    _cache["path"], _cache["model"] = path, model
    return model


def is_model_loaded():
    return _cache["model"] is not None


def model_status():
    try:
        _get_model()
        return {"loaded": True, "path": model_path(), "error": None}
    except ModelNotLoadedError as exc:
        return {"loaded": False, "path": model_path(), "error": str(exc)}


def model_metadata():
    status = model_status()
    meta = {}
    if status["loaded"]:
        meta = getattr(_cache["model"], "rulelock_metadata_", {}) or {}
    return {
        "model": "IsolationForest",
        "loaded": status["loaded"],
        "error": status["error"],
        "trained_at": meta.get("trained_at"),
        "trained_with_sklearn": meta.get("sklearn_version"),
        "sklearn_version": sklearn.__version__,
        "thresholds": thresholds(),
        "features": FEATURE_NAMES,
        "feature_ranges": {k: list(v) for k, v in TRAINING_RANGES.items()},
        "training_data": meta.get("training_data", "synthetic normal sessions only; evaluation is synthetic and circular"),
    }


def score_session(features):
    """features: dict with the four feature names (missing or bad values become defaults, values are clipped).
    Returns (raw_score, is_anomaly)."""
    model = _get_model()
    raw = float(model.decision_function(session_to_features(features))[0])
    return raw, bool(raw < thresholds()["hold"])
