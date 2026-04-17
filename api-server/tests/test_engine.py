"""
Unit tests for engine.py
EmbeddingEngine.embed, EmbeddingEngine.cosine
"""

import numpy as np
import pytest
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from engine import EmbeddingEngine


@pytest.fixture(scope="module")
def eng():
    return EmbeddingEngine()


# embed()

class TestEmbed:
    def test_returns_numpy_array(self, eng):
        emb = eng.embed("Title", "Some content about AI.")
        assert isinstance(emb, np.ndarray)

    def test_dtype_is_float32(self, eng):
        emb = eng.embed("Title", "Content here.")
        assert emb.dtype == np.float32

    def test_output_is_1d(self, eng):
        emb = eng.embed("Title", "Content here.")
        assert emb.ndim == 1

    def test_output_is_non_zero(self, eng):
        emb = eng.embed("Title", "Content here.")
        assert np.any(emb != 0)

    def test_empty_content_does_not_raise(self, eng):
        emb = eng.embed("Title", "")
        assert emb.ndim == 1

    def test_empty_title_does_not_raise(self, eng):
        emb = eng.embed("", "Some content.")
        assert emb.ndim == 1

    def test_long_content_handled_gracefully(self, eng):
        long_text = "word " * 5000
        emb = eng.embed("Title", long_text)
        assert emb.ndim == 1

    def test_different_texts_produce_different_embeddings(self, eng):
        emb_a = eng.embed("Politics",   "The election results were announced.")
        emb_b = eng.embed("Technology", "A new chip architecture was released.")
        assert not np.allclose(emb_a, emb_b)

    def test_same_text_produces_same_embedding(self, eng):
        emb_a = eng.embed("Title", "Identical content.")
        emb_b = eng.embed("Title", "Identical content.")
        assert np.allclose(emb_a, emb_b)

    def test_tail_content_included_for_long_articles(self, eng):
        """
        engine.py concatenates head (1600 chars) + tail (last 400 chars) for
        content longer than 2000 chars. Changing only the tail should shift
        the embedding.
        """
        base   = "a " * 1100            # 2200 chars
        tail_a = base + "unique ending alpha"
        tail_b = base + "unique ending beta"
        emb_a = eng.embed("T", tail_a)
        emb_b = eng.embed("T", tail_b)
        assert not np.allclose(emb_a, emb_b)



# cosine() static method

class TestCosineStatic:
    def test_identical_vectors_return_1(self):
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert EmbeddingEngine.cosine(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors_return_0(self):
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        assert EmbeddingEngine.cosine(a, b) == pytest.approx(0.0)

    def test_opposite_vectors_return_minus_1(self):
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([-1.0, 0.0], dtype=np.float32)
        assert EmbeddingEngine.cosine(a, b) == pytest.approx(-1.0)

    def test_returns_python_float(self):
        v = np.array([1.0, 0.0], dtype=np.float32)
        result = EmbeddingEngine.cosine(v, v)
        assert isinstance(result, float)

    def test_consistent_with_numpy_dot(self):
        rng = np.random.default_rng(0)
        a = rng.standard_normal(384).astype(np.float32)
        b = rng.standard_normal(384).astype(np.float32)
        # Engine cosine assumes pre-normalised vectors; normalise first
        a /= np.linalg.norm(a)
        b /= np.linalg.norm(b)
        assert EmbeddingEngine.cosine(a, b) == pytest.approx(float(np.dot(a, b)), abs=1e-6)
