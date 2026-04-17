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
        result = normalize_url("HTTPS://Example.COM/Path")
        assert result.startswith("https://example.com/")

    def test_strips_fragment(self):
        result = normalize_url("https://example.com/page#section")
        assert "#" not in result

    def test_strips_utm_source(self):
        result = normalize_url("https://example.com/page?utm_source=twitter")
        assert "utm_source" not in result

    def test_strips_all_utm_variants(self):
        url = "https://example.com/?utm_source=x&utm_medium=y&utm_campaign=z&utm_term=a&utm_content=b"
        result = normalize_url(url)
        assert "utm_" not in result

    def test_strips_ref_param(self):
        result = normalize_url("https://example.com/page?ref=homepage")
        assert "ref=" not in result

    def test_strips_cmpid_ocid_taid_rpc(self):
        url = "https://example.com/?cmpid=a&ocid=b&taid=c&rpc=d"
        result = normalize_url(url)
        for key in ("cmpid", "ocid", "taid", "rpc"):
            assert key not in result

    def test_preserves_non_tracking_params(self):
        result = normalize_url("https://example.com/search?q=python&page=2")
        assert "q=python" in result
        assert "page=2" in result

    def test_strips_trailing_slash_on_path(self):
        assert normalize_url("https://example.com/page/") == "https://example.com/page"

    def test_preserves_root_slash(self):
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_empty_string_returned_unchanged(self):
        assert normalize_url("") == ""

    def test_idempotent(self):
        url = "https://www.example.com/path?q=test&utm_source=x#frag"
        once  = normalize_url(url)
        twice = normalize_url(once)
        assert once == twice

    def test_mixed_tracking_and_real_params(self):
        url = "https://example.com/a?utm_source=x&cmpid=y&keep=1&ref=foo"
        result = normalize_url(url)
        assert "keep=1" in result
        assert "utm_source" not in result
        assert "cmpid"     not in result
        assert "ref="      not in result


# save_article / get_article_by_url

class TestSaveAndGetArticle:
    def test_save_and_retrieve_by_url(self, isolated_storage):
        art = make_article()
        save_article(art, make_random_embedding(0), user_id="user1")
        result = get_article_by_url(art.url, "user1")
        assert result is not None
        assert result["title"] == art.title

    def test_returns_none_for_unknown_url(self, isolated_storage):
        assert get_article_by_url("https://unknown.com/x", "user1") is None

    def test_user_isolation_on_get(self, isolated_storage):
        art = make_article()
        save_article(art, make_random_embedding(0), user_id="alice")
        assert get_article_by_url(art.url, "bob") is None

    def test_duplicate_url_ignored(self, isolated_storage):
        art = make_article()
        emb = make_random_embedding(0)
        save_article(art, emb, user_id="user1")
        save_article(art, emb, user_id="user1") # second write - ignored
        _, urls, _, _, _ = load_all("user1")
        assert len(urls) == 1

    def test_embedding_round_trip_fidelity(self, isolated_storage):
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
        # Lookup with the raw URL should still work (storage normalises it)
        result = get_article_by_url(raw_url, "user1")
        assert result is not None


# load_all

class TestLoadAll:
    def test_empty_user_returns_nones(self, isolated_storage):
        titles, urls, domains, timestamps, embs = load_all("nobody")
        assert titles == []
        assert embs is None

    def test_returns_correct_count(self, isolated_storage):
        for i in range(4):
            art = make_article(url=f"https://example.com/article-{i}", title=f"Article {i}")
            save_article(art, make_random_embedding(i), user_id="user1")
        titles, urls, *_ = load_all("user1")
        assert len(titles) == 4
        assert len(urls)   == 4

    def test_user_data_isolated_from_other_users(self, isolated_storage):
        save_article(make_article(url="https://a.com/1"), make_random_embedding(0), user_id="alice")
        save_article(make_article(url="https://b.com/2"), make_random_embedding(1), user_id="bob")
        _, alice_urls, _, _, _ = load_all("alice")
        _, bob_urls,   _, _, _ = load_all("bob")
        assert len(alice_urls) == 1
        assert len(bob_urls)   == 1
        assert alice_urls != bob_urls

    def test_embeddings_matrix_shape(self, isolated_storage):
        for i in range(3):
            art = make_article(url=f"https://example.com/{i}")
            save_article(art, make_random_embedding(i), user_id="user1")
        _, _, _, _, embs = load_all("user1")
        assert embs is not None
        assert embs.shape == (3, 384)


# get_embeddings_by_urls

class TestGetEmbeddingsByUrls:
    def test_empty_list_returns_empty(self, isolated_storage):
        assert get_embeddings_by_urls([]) == []

    def test_returns_embedding_for_known_url(self, isolated_storage):
        art = make_article()
        emb = make_random_embedding(5)
        save_article(art, emb, user_id="user1")
        results = get_embeddings_by_urls([normalize_url(art.url)])
        assert len(results) == 1
        assert np.allclose(results[0], emb, atol=1e-5)

    def test_unknown_url_not_included(self, isolated_storage):
        results = get_embeddings_by_urls(["https://not-in-db.com/x"])
        assert results == []

    def test_multiple_urls_returned_in_bulk(self, isolated_storage):
        urls = []
        for i in range(3):
            art = make_article(url=f"https://example.com/article-{i}")
            save_article(art, make_random_embedding(i), user_id="user1")
            urls.append(normalize_url(art.url))
        results = get_embeddings_by_urls(urls)
        assert len(results) == 3