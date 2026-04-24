"""
Unit tests for storage.py
Covers: normalize_url, save_article, get_article_by_url,
        load_all, get_embeddings_by_urls
"""

import numpy as np
import pytest
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from storage import normalize_url, save_article, get_article_by_url, load_all, get_embeddings_by_urls
from helpers import make_article, make_random_embedding


# normalize_url

class TestNormalizeUrl:
    def test_strips_www(self):
        assert normalize_url("https://www.example.com/path") == "https://example.com/path"

    def test_lowercases_scheme_and_host(self):
        assert normalize_url("HTTPS://Example.COM/Path").startswith("https://example.com/")

    def test_strips_fragment(self):
        assert "#" not in normalize_url("https://example.com/page#section")

    def test_strips_utm_params(self):
        url = "https://example.com/?utm_source=x&utm_medium=y&utm_campaign=z"
        assert "utm_" not in normalize_url(url)

    def test_strips_ref_param(self):
        assert "ref=" not in normalize_url("https://example.com/page?ref=homepage")

    def test_strips_cmpid_ocid_taid_rpc(self):
        url = "https://example.com/?cmpid=a&ocid=b&taid=c&rpc=d"
        result = normalize_url(url)
        for key in ("cmpid", "ocid", "taid", "rpc"):
            assert key not in result

    def test_strips_at_tracking_params(self):
        url = "https://example.com/?at_medium=natural&at_campaign=test"
        assert "at_medium" not in normalize_url(url)

    def test_strips_fbclid_gclid(self):
        url = "https://example.com/?fbclid=abc&gclid=xyz"
        result = normalize_url(url)
        assert "fbclid" not in result
        assert "gclid" not in result

    def test_preserves_non_tracking_params(self):
        result = normalize_url("https://example.com/search?q=python&page=2")
        assert "q=python" in result
        assert "page=2" in result

    def test_strips_trailing_slash(self):
        assert normalize_url("https://example.com/page/") == "https://example.com/page"

    def test_preserves_root_slash(self):
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_empty_string_unchanged(self):
        assert normalize_url("") == ""

    def test_idempotent(self):
        url = "https://www.example.com/path?q=test&utm_source=x#frag"
        once = normalize_url(url)
        assert once == normalize_url(once)

    def test_mixed_tracking_and_real_params(self):
        url = "https://example.com/a?utm_source=x&cmpid=y&keep=1&ref=foo"
        result = normalize_url(url)
        assert "keep=1" in result
        assert "utm_source" not in result
        assert "cmpid" not in result
        assert "ref=" not in result


# save_article / get_article_by_url

class TestSaveAndGetArticle:
    def test_save_and_retrieve(self, isolated_storage):
        art = make_article()
        save_article(art, make_random_embedding(0), user_id="user1")
        result = get_article_by_url(art.url, "user1")
        assert result is not None
        assert result["title"] == art.title

    def test_returns_none_for_unknown_url(self, isolated_storage):
        assert get_article_by_url("https://unknown.com/x", "user1") is None

    def test_user_isolation(self, isolated_storage):
        art = make_article()
        save_article(art, make_random_embedding(0), user_id="alice")
        assert get_article_by_url(art.url, "bob") is None

    def test_duplicate_url_not_duplicated(self, isolated_storage):
        art = make_article()
        emb = make_random_embedding(0)
        save_article(art, emb, user_id="user1")
        save_article(art, emb, user_id="user1")
        _, urls, _, _, _,*_ = load_all("user1")
        assert len(urls) == 1

    def test_embedding_round_trip(self, isolated_storage):
        art = make_article()
        emb = make_random_embedding(99)
        save_article(art, emb, user_id="user1")
        result = get_article_by_url(art.url, "user1")
        assert result["embedding"] is not None
        assert np.allclose(result["embedding"], emb, atol=1e-5)

    def test_url_normalised_on_save(self, isolated_storage):
        raw_url = "https://www.example.com/article?utm_source=tw#top"
        art = make_article(url=raw_url)
        save_article(art, make_random_embedding(0), user_id="user1")
        assert get_article_by_url(raw_url, "user1") is not None

    def test_metadata_fields_saved(self, isolated_storage):
        art = make_article(domain="news.example.com", timestamp="2024-06-01T00:00:00Z")
        save_article(art, make_random_embedding(0), user_id="user1")
        result = get_article_by_url(art.url, "user1")
        assert result["domain"] == art.domain
        assert result["timestamp"] == art.timestamp


# load_all

class TestLoadAll:
    def test_empty_user_returns_none_embeddings(self, isolated_storage):
        titles, urls, domains, timestamps, embs,*_ = load_all("nobody")
        assert titles == []
        assert embs is None

    def test_returns_correct_count(self, isolated_storage):
        for i in range(4):
            save_article(
                make_article(url=f"https://example.com/{i}", title=f"Article {i}"),
                make_random_embedding(i),
                user_id="user1",
            )
        titles, urls, *_ = load_all("user1")
        assert len(titles) == 4
        assert len(urls) == 4

    def test_user_data_isolated(self, isolated_storage):
        save_article(make_article(url="https://a.com/1"), make_random_embedding(0), user_id="alice")
        save_article(make_article(url="https://b.com/2"), make_random_embedding(1), user_id="bob")
        _, alice_urls, _, _, _,*_ = load_all("alice")
        _, bob_urls, _, _, _,*_ = load_all("bob")
        assert len(alice_urls) == 1
        assert len(bob_urls) == 1
        assert alice_urls != bob_urls

    def test_embeddings_matrix_shape(self, isolated_storage):
        for i in range(3):
            save_article(make_article(url=f"https://example.com/{i}"), make_random_embedding(i), user_id="user1")
        _, _, _, _, embs,*_ = load_all("user1")
        assert embs is not None
        assert embs.shape == (3, 384)


# get_embeddings_by_urls

class TestGetEmbeddingsByUrls:
    def test_empty_list_returns_empty(self, isolated_storage):
        assert get_embeddings_by_urls("user1", []) == []

    def test_returns_embedding_for_known_url(self, isolated_storage):
        art = make_article()
        emb = make_random_embedding(5)
        save_article(art, emb, user_id="user1")
        results = get_embeddings_by_urls("user1", [normalize_url(art.url)])
        assert len(results) == 1
        assert np.allclose(results[0], emb, atol=1e-5)

    def test_unknown_url_not_included(self, isolated_storage):
        assert get_embeddings_by_urls("user1", ["https://not-in-db.com/x"]) == []

    def test_multiple_urls_returned(self, isolated_storage):
        urls = []
        for i in range(3):
            art = make_article(url=f"https://example.com/article-{i}")
            save_article(art, make_random_embedding(i), user_id="user1")
            urls.append(normalize_url(art.url))
        assert len(get_embeddings_by_urls("user1", urls)) == 3

    def test_user_isolation(self, isolated_storage):
        art = make_article(url="https://example.com/shared")
        save_article(art, make_random_embedding(0), user_id="alice")
        # bob has no articles — should return nothing
        assert get_embeddings_by_urls("bob", [normalize_url(art.url)]) == []