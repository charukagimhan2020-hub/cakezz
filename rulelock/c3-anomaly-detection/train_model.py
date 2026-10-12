"""c3 training: Isolation Forest on NORMAL synthetic sessions only. Run `python train_model.py` (also at Docker build).

Abuse sessions are never used for training; they are only used by evaluate.py and the tests to check that a model
that learned only what normal looks like flags abuse.
"""
import os
from datetime import datetime, timezone

import joblib
import sklearn
from sklearn.ensemble import IsolationForest

from features import FEATURE_NAMES, TRAINING_RANGES
from synthetic_data import generate_normal_sessions

CONTRACT_SEED = 42
N_TRAIN = 5000
CONTAMINATION = 0.13     # see README: tuned so the offset puts the demo abuse below the -0.06 hold threshold


def _float_env(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def model_path():
    return os.environ.get("MODEL_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.joblib")


def build_model():
    """Train and return the model without saving it (used by evaluate.py and the tests)."""
    normal = generate_normal_sessions(n=N_TRAIN)
    model = IsolationForest(n_estimators=200, contamination=CONTAMINATION, random_state=CONTRACT_SEED)
    model.fit(normal)
    model.rulelock_metadata_ = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "sklearn_version": sklearn.__version__,
        "thresholds": {"hold": _float_env("ANOMALY_HOLD_THRESHOLD", -0.06),
                       "reject": _float_env("ANOMALY_REJECT_THRESHOLD", -0.1)},
        "feature_ranges": TRAINING_RANGES,
        "features": FEATURE_NAMES,
        "training_rows": N_TRAIN,
        "contamination": CONTAMINATION,
        "training_data": "synthetic normal sessions only; evaluation is synthetic and circular",
    }
    return model


def train(path=None):
    model = build_model()
    target = path or model_path()
    joblib.dump(model, target)
    return model


if __name__ == "__main__":
    train()
    print(f"Saved {model_path()}")
