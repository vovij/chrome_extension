"""
Unit tests for pure helper functions in app.py.
Covers: _is_match, _dot, _bytes_to_floats
"""

import struct
import numpy as np
import pytest


# replicated helpers

TAU_EMBED = 0.7

def _is_match(E: float) -> bool:
    return E >= TAU_EMBED

def _dot(a, b):
    if not a or not b:
        return None
    return sum(x * y for x, y in zip(a, b))

def _bytes_to_floats(blob):
    if blob is None:
        return None
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


# _is_match

class TestIsMatch:
    def test_above_threshold_accepted(self):
        assert _is_match(0.8) is True

    def test_below_threshold_rejected(self):
        assert _is_match(0.5) is False

    def test_exactly_at_threshold_accepted(self):
        assert _is_match(0.7) is True

    def test_just_below_threshold_rejected(self):
        assert _is_match(0.6999) is False

    def test_just_above_threshold_accepted(self):
        assert _is_match(0.7001) is True

    def test_zero_rejected(self):
        assert _is_match(0.0) is False

    def test_one_accepted(self):
        assert _is_match(1.0) is True

    def test_returns_bool(self):
        assert isinstance(_is_match(0.8), bool)


# _dot

class TestDot:
    def test_basic_dot_product(self):
        assert _dot([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]) == pytest.approx(32.0)

    def test_orthogonal_vectors_return_zero(self):
        assert _dot([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_unit_vectors_return_one(self):
        assert _dot([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_none_first_returns_none(self):
        assert _dot(None, [1.0, 2.0]) is None

    def test_none_second_returns_none(self):
        assert _dot([1.0, 2.0], None) is None

    def test_empty_first_returns_none(self):
        assert _dot([], [1.0, 2.0]) is None

    def test_empty_second_returns_none(self):
        assert _dot([1.0, 2.0], []) is None

    def test_both_none_returns_none(self):
        assert _dot(None, None) is None

    def test_consistent_with_numpy(self):
        rng = np.random.default_rng(42)
        a = rng.standard_normal(64).tolist()
        b = rng.standard_normal(64).tolist()
        assert _dot(a, b) == pytest.approx(float(np.dot(a, b)), abs=1e-5)

    def test_first_article_dot_self_is_one_for_unit_vector(self):
        # simulates get_history: head_emb dot head_emb
        v = [1.0, 0.0, 0.0]
        assert _dot(v, v) == pytest.approx(1.0)


# _bytes_to_floats

class TestBytesToFloats:
    def test_none_returns_none(self):
        assert _bytes_to_floats(None) is None

    def test_single_float_round_trip(self):
        blob = struct.pack("1f", 3.14)
        result = _bytes_to_floats(blob)
        assert len(result) == 1
        assert result[0] == pytest.approx(3.14, abs=1e-5)

    def test_multiple_floats_round_trip(self):
        values = [1.0, 2.0, 3.0, 4.0]
        blob = struct.pack(f"{len(values)}f", *values)
        assert _bytes_to_floats(blob) == pytest.approx(values, abs=1e-6)

    def test_returns_list(self):
        blob = struct.pack("2f", 1.0, 2.0)
        assert isinstance(_bytes_to_floats(blob), list)

    def test_embedding_round_trip(self):
        emb = np.random.default_rng(0).standard_normal(384).astype(np.float32)
        result = _bytes_to_floats(emb.tobytes())
        assert len(result) == 384
        assert result == pytest.approx(emb.tolist(), abs=1e-6)

    def test_consistent_with_numpy_frombuffer(self):
        emb = np.random.default_rng(7).standard_normal(16).astype(np.float32)
        blob = emb.tobytes()
        assert _bytes_to_floats(blob) == pytest.approx(
            np.frombuffer(blob, dtype=np.float32).tolist(), abs=1e-6
        )