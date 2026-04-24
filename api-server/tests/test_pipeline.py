"""
Integration tests for the SeenIt backend.

Wires together engine, storage, and cluster_utils to verify the full
pipeline end-to-end without spinning up FastAPI or hitting a real ML model.
The EmbeddingEngine is backed by FakeSentenceTransformer from conftest.py.
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


# embed - save - retrieve round-trip

class TestEmbedSaveRetrieve:
    def test_embedding_survives_db_round_trip(self, eng, isolated_storage):
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
        assert result["title"] == art.title
        assert result["domain"] == art.domain


# similarity scoring via matrix multiplication (mirrors app.py _find_matches)

class TestSimilarityScoring:
    def test_dot_product_returns_scores_for_all_stored(self, eng, isolated_storage):
        for i in range(5):
            art = make_article(url=f"https://example.com/{i}", title=f"Article {i}")
            save_article(art, eng.embed(art.title, art.content), user_id="bob")

        new_emb = eng.embed("New Article", "Some content.")
        _, _, _, _, embs,*_ = load_all("bob")
        sims = embs @ new_emb
        assert len(sims) == 5
        assert all(-1.0 <= float(s) <= 1.0 for s in sims)

    def test_user_data_isolated_from_other_users(self, eng, isolated_storage):
        for i in range(3):
            save_article(make_article(url=f"https://a.com/{i}"), eng.embed("T", "C"), user_id="userA")
        for i in range(10):
            save_article(make_article(url=f"https://b.com/{i}"), eng.embed("T", "C"), user_id="userB")

        _, urls_a, _, _, embs_a, *_ = load_all("userA")
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

        query_art = arts[1]
        query_emb = eng.embed(query_art.title, query_art.content)
        titles, urls, _, _, embs , *_ = load_all("carol")
        best_idx = int(np.argmax(embs @ query_emb))
        assert urls[best_idx] == normalize_url(query_art.url)


# cluster centroid + novelty pipeline

class TestCentroidNoveltyPipeline:
    def test_novelty_zero_when_identical_to_cluster(self, eng, isolated_storage):
        art = make_article(url="https://example.com/topic-a")
        emb = eng.embed(art.title, art.content)
        save_article(art, emb, user_id="dave")
        centroid = compute_centroid([emb.tolist()])
        assert compute_novelty_score(emb, centroid) == pytest.approx(0.0, abs=1e-5)

    def test_novelty_higher_for_orthogonal_article(self, eng, isolated_storage):
        dim = 384
        e0 = np.zeros(dim, dtype=np.float32); e0[0] = 1.0
        e1 = np.zeros(dim, dtype=np.float32); e1[1] = 1.0

        for i in range(3):
            art = make_article(url=f"https://example.com/cluster-{i}")
            save_article(art, e0.copy(), user_id="eve")

        cluster_urls = [normalize_url(f"https://example.com/cluster-{i}") for i in range(3)]
        db_embs = get_embeddings_by_urls("eve", cluster_urls)
        centroid = compute_centroid([e.tolist() for e in db_embs])

        close_novelty = compute_novelty_score(e0.copy(), centroid)
        far_novelty = compute_novelty_score(e1, centroid)
        assert far_novelty > close_novelty

    def test_novelty_score_in_valid_range(self, eng, isolated_storage):
        for i in range(5):
            art = make_article(url=f"https://example.com/a{i}", title=f"Climate article {i}")
            save_article(art, eng.embed(art.title, art.content), user_id="frank")

        urls = [normalize_url(f"https://example.com/a{i}") for i in range(5)]
        embs = get_embeddings_by_urls("frank", urls)
        centroid = compute_centroid([e.tolist() for e in embs])
        novelty = compute_novelty_score(eng.embed("Space news", "Rockets launched."), centroid)
        assert 0.0 <= novelty <= 1.0

    def test_centroid_matches_manual_mean(self, eng, isolated_storage):
        arts = [make_article(url=f"https://example.com/c{i}") for i in range(4)]
        raw_embs = []
        for art in arts:
            emb = eng.embed(art.title, art.content)
            save_article(art, emb, user_id="grace")
            raw_embs.append(emb)

        urls = [normalize_url(a.url) for a in arts]
        db_embs = get_embeddings_by_urls("grace", urls)
        centroid = compute_centroid([e.tolist() for e in db_embs])
        expected = np.array(raw_embs).mean(axis=0).tolist()
        assert centroid == pytest.approx(expected, abs=1e-4)


# duplicate URL handling

class TestDuplicateUrlPipeline:
    def test_duplicate_not_double_counted(self, eng, isolated_storage):
        art = make_article(url="https://example.com/dupe")
        emb = eng.embed(art.title, art.content)
        save_article(art, emb, user_id="henry")
        save_article(art, emb, user_id="henry")
        _, urls, _, _, _,*_ = load_all("henry")
        assert urls.count(normalize_url(art.url)) == 1

    def test_article_retrievable_after_second_save(self, eng, isolated_storage):
        art = make_article(url="https://example.com/stable")
        emb = eng.embed(art.title, art.content)
        save_article(art, emb, user_id="ivy")
        save_article(art, emb, user_id="ivy")
        result = get_article_by_url(art.url, "ivy")
        assert result is not None
        assert result["title"] == art.title