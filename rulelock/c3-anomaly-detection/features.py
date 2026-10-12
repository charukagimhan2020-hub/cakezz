"""c3 features: the four session features, their defaults, and the clipping to the training ranges.

Reused from the team's deployed data-collection/features.py. Changes: a non-dict session, bool values and
NaN/inf no longer cause errors (they become defaults); the helpers are kept because c1 may use them.
c1 builds the feature values from the database (see README.md for what to count).
"""
from datetime import datetime, timedelta, timezone

import numpy as np

FEATURE_NAMES = [
    "coupon_attempts_per_session",
    "avg_seconds_between_requests",
    "distinct_accounts_same_device",
    "distinct_addresses_same_phone",
]
FEATURE_DEFAULTS = {
    "coupon_attempts_per_session": 0,
    "avg_seconds_between_requests": 30,
    "distinct_accounts_same_device": 1,
    "distinct_addresses_same_phone": 1,
}
# Bounds used by BOTH training and scoring: a wild input value (9999 coupons) is clipped to the edge.
TRAINING_RANGES = {
    "coupon_attempts_per_session": (0.0, 15.0),
    "avg_seconds_between_requests": (1.0, 600.0),
    "distinct_accounts_same_device": (1.0, 8.0),
    "distinct_addresses_same_phone": (1.0, 8.0),
}


def recent_session_events(rows, now=None):
    """Events of one session from the trailing 30 minutes with a readable created_at, oldest first."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=30)
    selected = []
    for row in rows or []:
        value = row.get("created_at") if isinstance(row, dict) else None
        if not value:
            continue
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if cutoff <= stamp <= now:
            selected.append((stamp, row))
    return sorted(selected, key=lambda item: item[0])


def average_seconds_between_requests(rows, now=None):
    """(last - first) / (n - 1) over the recent session events. Fewer than 3 events -> the default (30)."""
    recent = recent_session_events(rows, now)
    if len(recent) < 3:
        return FEATURE_DEFAULTS["avg_seconds_between_requests"]
    elapsed = (recent[-1][0] - recent[0][0]).total_seconds()
    return max(elapsed / (len(recent) - 1), 0.0)


def session_to_features(session) -> np.ndarray:
    """dict of feature values -> array of shape (1, 4), in FEATURE_NAMES order, clipped to TRAINING_RANGES.
    Missing, non-numeric, bool, NaN or infinite values become the defaults."""
    if not isinstance(session, dict):
        session = {}
    values = []
    for name in FEATURE_NAMES:
        value = session.get(name, FEATURE_DEFAULTS[name])
        try:
            numeric = float(value) if not isinstance(value, bool) else float("nan")
        except (TypeError, ValueError, OverflowError):
            numeric = float("nan")
        if not np.isfinite(numeric):
            numeric = float(FEATURE_DEFAULTS[name])
        low, high = TRAINING_RANGES[name]
        values.append(float(np.clip(numeric, low, high)))
    return np.asarray([values], dtype=float)
