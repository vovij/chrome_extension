"""
Integration tests for SeenIt backend.

These tests wire together the real modules (engine, storage, cluster_utils)
and verify that the full pipeline behaves correctly end-to-end, without
spinning up FastAPI or hitting a real ML model.

The EmbeddingEngine is backed by the deterministic FakeSentenceTransformer
defined in conftest.py, so tests are fast and reproducible.
"""

import numpy as np
import pytest
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from engine import EmbeddingEngine
from storage import save_article, load_all, get_article_by_url, get_embeddings_by_urls, normalize_url
from cluster_utils import compute_centroid, compute_novelty_score
from helpers import make_article, make_random_embedding


@pytest.fixture(scope="module")
def eng():
    return EmbeddingEngine()



# Embed, Save, Retrieve round-trip

class TestEmbedSaveRetrieve:
    def test_saved_embedding_survives_db_round_trip(self, eng, isolated_storage):
        art = make_article(url="https://news.example.com/ai-chips")
        emb = eng.embed(art.title, art.content)

        save_article(art, emb, user_id="alice")
        result = get_article_by_url(art.url, "alice")

        assert result is not None
        assert np.allclose(result["embedding"], emb, atol=1e-5)

    def test_metadata_survives_db_round_trip(self, eng, isolated_storage):
        art = make_article(
            url="https://tech.example.com/llms",
            title="Large Language Models Explained",
            domain="tech.example.com",
        )
        emb = eng.embed(art.title, art.content)
        save_article(art, emb, user_id="alice")

        result = get_article_by_url(art.url, "alice")
        assert result["title"]  == art.title
        assert result["domain"] == art.domain



# Similarity scoring via matrix multiplication (mirrors app.py logic)

class TestSimilarityScoring:
    """
    Verifies that the dot-product similarity search (embs @ new_emb) works
    correctly after save/load, and that user data is isolated.
    """

    def test_dot_product_returns_scores_for_all_stored_articles(self, eng, isolated_storage):
        articles = [
            make_article(url=f"https://example.com/{i}", title=f"Article {i}")
            for i in range(5)
        ]
        for art in articles:
            save_article(art, eng.embed(art.title, art.content), user_id="bob")

        new_art = make_article(url="https://example.com/new", title="New Article")
        new_emb = eng.embed(new_art.title, new_art.content)

        _, _, _, _, embs = load_all("bob")
        sims = embs @ new_emb

        assert len(sims) == 5
        assert all(-1.0 <= float(s) <= 1.0 for s in sims)

    def test_user_a_scores_not_affected_by_user_b_data(self, eng, isolated_storage):
        for i in range(3):
            art = make_article(url=f"https://a.com/{i}")
            save_article(art, eng.embed(art.title, art.content), user_id="userA")

        for i in range(10):
            art = make_article(url=f"https://b.com/{i}")
            save_article(art, eng.embed(art.title, art.content), user_id="userB")

        _, urls_a, _, _, embs_a = load_all("userA")
        assert len(urls_a) == 3
        assert embs_a.shape[0] == 3

    def test_self_similarity_is_highest(self, eng, isolated_storage):
        arts = [
            make_article(url="https://x.com/sports",  title="Football match results"),
            make_article(url="https://x.com/science", title="Black hole discovery"),
            make_article(url="https://x.com/finance", title="Stock market crash"),
        ]
        for art in arts:
            save_article(art, eng.embed(art.title, art.content), user_id="carol")

        query_art = arts[1]  # science article
        query_emb = eng.embed(query_art.title, query_art.content)

        titles, urls, _, _, embs = load_all("carol")
        sims = embs @ query_emb

        best_idx = int(np.argmax(sims))
        assert urls[best_idx] == normalize_url(query_art.url)



# Cluster centroid + novelty pipeline

class TestCentroidNoveltyPipeline:
    def test_novelty_zero_when_article_identical_to_cluster(self, eng, isolated_storage):
        art = make_article(url="https://example.com/topic-a", title="Topic A")
        emb = eng.embed(art.title, art.content)
        save_article(art, emb, user_id="dave")

        centroid = compute_centroid([emb.tolist()])
        novelty  = compute_novelty_score(emb, centroid)
        assert novelty == pytest.approx(0.0, abs=1e-5)

    def test_novelty_higher_for_unrelated_article(self, eng, isolated_storage):
        """
        Use controlled embeddings so the geometry is deterministic regardless
        of what the (fake) encoder returns. We build a cluster whose centroid
        points along axis-0, then compare a close vector (low novelty) with
        an orthogonal one (high novelty).
        """
        dim = 384

        # Cluster: three vectors tightly packed around axis-0
        cluster_embs_raw = [make_random_embedding(seed=s, dim=dim) for s in range(3)]
        # Project them all onto axis-0 direction so centroid is very close to e0
        e0 = np.zeros(dim, dtype=np.float32); e0[0] = 1.0
        cluster_embs_raw = [e0.copy() for _ in range(3)]   # perfect cluster

        for i, art_emb in enumerate(cluster_embs_raw):
            art = make_article(url=f"https://example.com/cluster-{i}")
            save_article(art, art_emb, user_id="eve")

        cluster_urls = [normalize_url(f"https://example.com/cluster-{i}") for i in range(3)]
        db_embs  = get_embeddings_by_urls(cluster_urls)
        centroid = compute_centroid([e.tolist() for e in db_embs])

        # Close to centroid - low novelty
        close_emb = e0.copy()
        close_nov = compute_novelty_score(close_emb, centroid)

        # Orthogonal to centroid - high novelty
        e1 = np.zeros(dim, dtype=np.float32); e1[1] = 1.0
        far_nov = compute_novelty_score(e1, centroid)

        assert far_nov > close_nov

    def test_novelty_score_in_valid_range(self, eng, isolated_storage):
        arts = [
            make_article(url=f"https://example.com/a{i}", title=f"Climate change article {i}")
            for i in range(5)
        ]
        for art in arts:
            save_article(art, eng.embed(art.title, art.content), user_id="frank")

        urls  = [normalize_url(a.url) for a in arts]
        embs  = get_embeddings_by_urls(urls)
        centroid = compute_centroid([e.tolist() for e in embs])

        new_emb  = eng.embed("A completely different topic", "Space exploration news.")
        novelty  = compute_novelty_score(new_emb, centroid)
        assert 0.0 <= novelty <= 1.0

    def test_centroid_of_saved_embeddings_matches_manual_mean(self, eng, isolated_storage):
        arts = [
            make_article(url=f"https://example.com/c{i}", title=f"Article {i}")
            for i in range(4)
        ]
        raw_embs = []
        for art in arts:
            emb = eng.embed(art.title, art.content)
            save_article(art, emb, user_id="grace")
            raw_embs.append(emb)

        urls = [normalize_url(a.url) for a in arts]
        db_embs  = get_embeddings_by_urls(urls)
        centroid = compute_centroid([e.tolist() for e in db_embs])

        expected = np.array(raw_embs).mean(axis=0).tolist()
        assert centroid == pytest.approx(expected, abs=1e-4)



# Duplicate URL handling across the pipeline

class TestDuplicateUrlPipeline:
    def test_duplicate_article_not_double_counted_in_similarity(self, eng, isolated_storage):
        art = make_article(url="https://example.com/dupe")
        emb = eng.embed(art.title, art.content)

        save_article(art, emb, user_id="henry")
        save_article(art, emb, user_id="henry")   # second write ignored

        _, urls, _, _, _ = load_all("henry")
        assert urls.count(normalize_url(art.url)) == 1

    def test_existing_article_retrievable_after_failed_second_save(self, eng, isolated_storage):
        art = make_article(url="https://example.com/stable")
        emb = eng.embed(art.title, art.content)

        save_article(art, emb, user_id="ivy")
        save_article(art, emb, user_id="ivy")   # no-op

        result = get_article_by_url(art.url, "ivy")
        assert result is not None
        assert result["title"] == art.title