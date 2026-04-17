"""
Unit tests for cluster_utils.py
Covers: compute_centroid, cosine_similarity, compute_novelty_score
"""

import numpy as np
import pytest
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from cluster_utils import compute_centroid, cosine_similarity, compute_novelty_score


# compute_centroid
class TestComputeCentroid:
    def test_empty_input_returns_empty(self):
        assert compute_centroid([]) == []

    def test_single_vector_returned_unchanged(self):
        v = [1.0, 2.0, 3.0]
        assert compute_centroid([v]) == pytest.approx(v)

    def test_two_identical_vectors(self):
        v = [0.5, 0.5, 0.5]
        assert compute_centroid([v, v]) == pytest.approx(v)

    def test_element_wise_mean(self):
        a = [2.0, 4.0]
        b = [4.0, 8.0]
        assert compute_centroid([a, b]) == pytest.approx([3.0, 6.0])

    def test_opposite_vectors_centroid_is_zero(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert compute_centroid([a, b]) == pytest.approx([0.0, 0.0])

    def test_returns_python_list(self):
        result = compute_centroid([[1.0, 2.0]])
        assert isinstance(result, list)

    def test_high_dimensional_vectors(self):
        rng = np.random.default_rng(0)
        vecs = rng.standard_normal((10, 384)).tolist()
        c = compute_centroid(vecs)
        expected = np.array(vecs).mean(axis=0).tolist()
        assert c == pytest.approx(expected, abs=1e-5)



# cosine_similarity

class TestCosineSimilarity:
    def test_identical_vectors_return_1(self):
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors_return_0(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors_return_minus_1(self):
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_none_first_arg_returns_0(self):
        assert cosine_similarity(None, [1.0, 2.0]) == 0.0

    def test_none_second_arg_returns_0(self):
        assert cosine_similarity([1.0, 2.0], None) == 0.0

    def test_empty_arrays_return_0(self):
        assert cosine_similarity([], []) == 0.0

    def test_zero_vector_returns_0(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_numpy_arrays_accepted(self):
        a = np.array([1.0, 1.0])
        b = np.array([1.0, 1.0])
        assert cosine_similarity(a, b) == pytest.approx(1.0)

    def test_is_symmetric(self):
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        assert cosine_similarity(a, b) == pytest.approx(cosine_similarity(b, a))

    def test_scale_invariant(self):
        a = [1.0, 0.0]
        assert cosine_similarity(a, [100.0, 0.0]) == pytest.approx(1.0)
        assert cosine_similarity(a, [0.001, 0.0]) == pytest.approx(1.0)

    def test_result_in_minus1_to_1(self):
        rng = np.random.default_rng(42)
        for _ in range(100):
            a = rng.standard_normal(64).tolist()
            b = rng.standard_normal(64).tolist()
            sim = cosine_similarity(a, b)
            assert -1.0 - 1e-9 <= sim <= 1.0 + 1e-9



# compute_novelty_score

class TestComputeNoveltyScore:
    def test_identical_embedding_gives_zero_novelty(self):
        v = [1.0, 0.0, 0.0]
        assert compute_novelty_score(v, v) == pytest.approx(0.0)

    def test_opposite_embedding_clamped_to_one(self):
        assert compute_novelty_score([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_embedding_gives_one(self):
        assert compute_novelty_score([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)

    def test_output_always_in_0_1(self):
        rng = np.random.default_rng(7)
        for _ in range(200):
            a = rng.standard_normal(64)
            b = rng.standard_normal(64)
            score = compute_novelty_score(a, b)
            assert 0.0 <= score <= 1.0, f"Out of range: {score}"

    def test_more_similar_means_less_novel(self):
        base  = np.array([1.0, 0.0, 0.0])
        close = np.array([0.99, 0.141, 0.0])   # 8 deg away
        far   = np.array([0.0,  1.0,  0.0])    # 90 deg away
        assert compute_novelty_score(base, close) < compute_novelty_score(base, far)

    def test_novelty_is_one_minus_cosine(self):
        a = [0.6, 0.8]
        b = [0.8, 0.6]
        expected = max(0.0, min(1.0, 1.0 - cosine_similarity(a, b)))
        assert compute_novelty_score(a, b) == pytest.approx(expected, abs=1e-6)
