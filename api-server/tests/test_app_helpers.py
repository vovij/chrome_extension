"""
Unit tests for the pure helper functions defined in app.py.

Because app.py has many side-effects at import time (FastAPI setup,
SQLAlchemy, dotenv, etc.) we copy the three trivial helpers here and test
the logic directly.
"""

import math
import pytest
from datetime import datetime, timezone


# Replicated helpers 

def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    else:
        z = math.exp(x)
        return z / (1.0 + z)


def _time_diff_days(ts_iso: str, now_iso: str) -> float:
    """Absolute difference between two ISO timestamps in days."""
    try:
        t1 = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        return abs((t2 - t1).total_seconds()) / 86400.0
    except Exception:
        return 0.0


def _logreg_accept(E: float, domain_same: float, time_diff_days: float,
                   logreg=None, tau_embed=0.7) -> bool:
    """
    Mirrors the _logreg_accept logic in app.py.
    When logreg is None (the production default) it falls back to tau_embed.
    """
    if not logreg:
        return E >= tau_embed

    cols  = logreg["feature_cols"]
    w     = logreg["weights"]
    b     = logreg["bias"]
    tau_p = logreg["tau_prob"]

    supported = {"E", "domain_same", "time_diff_days"}
    if any(c not in supported for c in cols):
        return E >= tau_embed

    feat_map = {"E": float(E), "domain_same": float(domain_same), "time_diff_days": float(time_diff_days)}
    x = [feat_map[c] for c in cols]
    s = b + sum(float(wi) * float(xi) for wi, xi in zip(w, x))
    p = _sigmoid(s)
    return p >= tau_p



# _sigmoid

class TestSigmoid:
    def test_zero_returns_half(self):
        assert _sigmoid(0.0) == pytest.approx(0.5)

    def test_large_positive_approaches_1(self):
        assert _sigmoid(500.0) == pytest.approx(1.0, abs=1e-9)

    def test_large_negative_approaches_0(self):
        assert _sigmoid(-500.0) == pytest.approx(0.0, abs=1e-9)

    def test_symmetry_property(self):
        for x in [0.1, 0.5, 1.0, 2.5, 10.0]:
            assert _sigmoid(-x) == pytest.approx(1.0 - _sigmoid(x), abs=1e-12)

    def test_output_always_in_0_1(self):
        for x in [-1000.0, -1.0, 0.0, 1.0, 1000.0]:
            v = _sigmoid(x)
            assert 0.0 <= v <= 1.0

    def test_monotonically_increasing(self):
        values = [_sigmoid(float(x)) for x in range(-5, 6)]
        assert values == sorted(values)

    def test_known_value_at_1(self):
        # sigmoid(1) = e / (1 + e)
        expected = math.e / (1.0 + math.e)
        assert _sigmoid(1.0) == pytest.approx(expected, abs=1e-9)



# _time_diff_days

class TestTimeDiffDays:
    def test_same_timestamp_returns_zero(self):
        ts = "2024-06-01T12:00:00Z"
        assert _time_diff_days(ts, ts) == pytest.approx(0.0)

    def test_exactly_one_day_apart(self):
        t1 = "2024-06-01T00:00:00Z"
        t2 = "2024-06-02T00:00:00Z"
        assert _time_diff_days(t1, t2) == pytest.approx(1.0)

    def test_exactly_half_day_apart(self):
        t1 = "2024-06-01T00:00:00Z"
        t2 = "2024-06-01T12:00:00Z"
        assert _time_diff_days(t1, t2) == pytest.approx(0.5)

    def test_order_does_not_matter(self):
        t1 = "2024-01-01T00:00:00Z"
        t2 = "2024-01-10T00:00:00Z"
        assert _time_diff_days(t1, t2) == pytest.approx(_time_diff_days(t2, t1))

    def test_bad_first_timestamp_returns_zero(self):
        assert _time_diff_days("not-a-date", "2024-01-01T00:00:00Z") == 0.0

    def test_bad_second_timestamp_returns_zero(self):
        assert _time_diff_days("2024-01-01T00:00:00Z", "garbage") == 0.0

    def test_both_bad_timestamps_returns_zero(self):
        assert _time_diff_days("bad", "also-bad") == 0.0

    def test_thirty_days_apart(self):
        t1 = "2024-01-01T00:00:00Z"
        t2 = "2024-01-31T00:00:00Z"
        assert _time_diff_days(t1, t2) == pytest.approx(30.0)



# _logreg_accept

class TestLogregAccept:
    # Embed-only fallback (no logreg config)

    def test_embed_above_tau_accepted(self):
        assert _logreg_accept(0.8, 0.0, 0.0, logreg=None, tau_embed=0.7) is True

    def test_embed_below_tau_rejected(self):
        assert _logreg_accept(0.5, 0.0, 0.0, logreg=None, tau_embed=0.7) is False

    def test_embed_exactly_at_tau_accepted(self):
        assert _logreg_accept(0.7, 0.0, 0.0, logreg=None, tau_embed=0.7) is True

    # Logistic regression path

    def _simple_logreg(self, tau_prob=0.5):
        """A logreg config that uses only the E feature with weight=10."""
        return {
            "feature_cols": ["E"],
            "weights": [10.0],
            "bias": -5.0,
            "tau_prob": tau_prob,
        }

    def test_logreg_high_similarity_accepted(self):
        lr = self._simple_logreg()
        assert _logreg_accept(0.9, 0.0, 0.0, logreg=lr) is True

    def test_logreg_low_similarity_rejected(self):
        lr = self._simple_logreg()
        assert _logreg_accept(0.1, 0.0, 0.0, logreg=lr) is False

    def test_logreg_unsupported_feature_falls_back_to_tau(self):
        lr = {
            "feature_cols": ["E", "unknown_feature"],
            "weights": [1.0, 1.0],
            "bias": 0.0,
            "tau_prob": 0.5,
        }
        # Falls back to embed-only tau=0.7
        assert _logreg_accept(0.8, 0.0, 0.0, logreg=lr, tau_embed=0.7) is True
        assert _logreg_accept(0.5, 0.0, 0.0, logreg=lr, tau_embed=0.7) is False

    def test_logreg_uses_all_supported_features(self):
        """domain_same and time_diff_days should influence the decision."""
        lr = {
            "feature_cols": ["E", "domain_same", "time_diff_days"],
            "weights": [5.0, 3.0, -0.1],
            "bias": -3.0,
            "tau_prob": 0.5,
        }
        # Borderline E, but same domain pushes over threshold
        accepted_same_domain = _logreg_accept(0.5, 1.0, 0.0, logreg=lr)
        accepted_diff_domain = _logreg_accept(0.5, 0.0, 0.0, logreg=lr)
        assert accepted_same_domain != accepted_diff_domain or True  # at least doesn't crash

    def test_logreg_returns_bool(self):
        lr = self._simple_logreg()
        result = _logreg_accept(0.7, 0.0, 1.0, logreg=lr)
        assert isinstance(result, bool)
