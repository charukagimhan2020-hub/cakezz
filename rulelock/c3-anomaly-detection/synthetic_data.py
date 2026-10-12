"""Synthetic sessions. THE DATA IS MADE UP: there is no real shop traffic behind it (see README.md).

Column order everywhere = features.FEATURE_NAMES:
  coupon_attempts_per_session, avg_seconds_between_requests, distinct_accounts_same_device, distinct_addresses_same_phone
"""
import numpy as np


def generate_normal_sessions(n=500, seed=42):
    """Normal shopping: 0 to a few coupon attempts, pauses of seconds to minutes, almost always 1 account / 1 address."""
    rng = np.random.default_rng(seed)
    return np.column_stack([
        rng.poisson(0.8, n).clip(0, 5),
        rng.lognormal(np.log(35), 1.3, n).clip(1, 600),      # broad, right-skewed: pauses of minutes are routine (sigma 1.0 -> 1.3)
        rng.choice([1, 2], n, p=[0.97, 0.03]),
        rng.choice([1, 2], n, p=[0.97, 0.03]),
    ])


def _abuse(n, rng, coupons, seconds, accounts, addresses):
    return np.column_stack([coupons(n, rng), seconds(n, rng), accounts(n, rng), addresses(n, rng)])


def generate_coupon_stacking(n=50, seed=7):
    """Demo abuse 1: 4 to 10 coupon attempts, 1 to 5 s apart. One account, one address."""
    rng = np.random.default_rng(seed)
    return _abuse(n, rng, lambda k, r: r.integers(4, 11, k), lambda k, r: r.uniform(1, 5, k),
                  lambda k, r: np.ones(k), lambda k, r: np.ones(k))


def generate_multi_account(n=50, seed=8):
    """Demo abuse 2: several accounts on one device (3 to 6), otherwise a normal-looking session."""
    rng = np.random.default_rng(seed)
    return _abuse(n, rng, lambda k, r: r.integers(0, 3, k), lambda k, r: r.uniform(20, 90, k),
                  lambda k, r: r.integers(3, 7, k), lambda k, r: np.ones(k))


def generate_cod_address_farming(n=50, seed=9):
    """Demo abuse 3: many COD orders with different addresses (3 to 7) on one phone, otherwise normal-looking."""
    rng = np.random.default_rng(seed)
    return _abuse(n, rng, lambda k, r: r.integers(0, 3, k), lambda k, r: r.uniform(20, 90, k),
                  lambda k, r: np.ones(k), lambda k, r: r.integers(3, 8, k))


def generate_abuse_sessions(n=50, seed=7):
    """The three demo abuse types mixed in equal parts (about n sessions)."""
    k = max(n // 3, 1)
    return np.vstack([generate_coupon_stacking(k, seed), generate_multi_account(k, seed + 1),
                      generate_cod_address_farming(n - 2 * k if n - 2 * k > 0 else k, seed + 2)])


def generate_demo_normal(n=200, seed=11):
    """The 'normal' definition used in the demo checks: 0 to 2 coupon attempts, 20 to 90 s, 1 account, 1 address."""
    rng = np.random.default_rng(seed)
    return np.column_stack([rng.integers(0, 3, n), rng.uniform(20, 90, n), np.ones(n), np.ones(n)])
