import os
import sqlite3
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlunsplit, urlsplit

import numpy as np


# tracking params to strip from URLs (matches popup.js/background.js)
TRACKING_KEYS_PREFIX = ("utm_", "at_")
DROP_QUERY_KEYS = {
    "ref", "cmpid", "ocid", "taid", "rpc",
    "at_medium", "at_campaign", "at_link_id", "at_link_type",
    "at_link_origin", "at_format", "at_ptr_name", "at_bbc_team",
    "fbclid", "gclid", "gbraid", "wbraid",
    "mc_cid", "mc_eid",
}


def normalize_url(url: str) -> str:
    if not url:
        return url

    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    netloc = (parts.netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    q = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        kl = k.lower()
        if kl.startswith(TRACKING_KEYS_PREFIX) or kl in DROP_QUERY_KEYS:
            continue
        q.append((k, v))

    return urlunsplit((scheme, netloc, path, urlencode(q, doseq=True), ""))


# db setup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

ARTICLES_DB_PATH = os.getenv("ARTICLES_DB_PATH", os.path.join(DATA_DIR, "articles.db"))

conn = sqlite3.connect(ARTICLES_DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    cluster_id TEXT,
    similarity REAL,
    url TEXT,
    title TEXT,
    content TEXT,
    domain TEXT,
    timestamp TEXT,
    embedding BLOB,
    UNIQUE(user_id, url)
)
""")
conn.commit()


def save_article(article, embedding: np.ndarray, user_id: str, cluster_id: str = None, similarity: float = None):
    cursor.execute("""
    INSERT INTO articles
    (user_id, url, title, content, domain, timestamp, embedding, cluster_id, similarity)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(user_id, url) DO UPDATE SET
        title = excluded.title,
        content = excluded.content,
        domain = excluded.domain,
        timestamp = excluded.timestamp,
        embedding = excluded.embedding,
        cluster_id = COALESCE(excluded.cluster_id, articles.cluster_id),
        similarity = COALESCE(excluded.similarity, articles.similarity)
    """, (
        user_id,
        normalize_url(article.url),
        article.title,
        article.content,
        article.domain,
        article.timestamp,
        embedding.tobytes(),
        normalize_url(cluster_id) if cluster_id else None,
        similarity,
    ))
    conn.commit()


def get_article_by_url(url: str, user_id: str) -> Optional[dict]:
    cursor.execute(
        "SELECT url, title, content, domain, timestamp, embedding FROM articles WHERE url = ? AND user_id = ?",
        (normalize_url(url), user_id),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "url": row[0],
        "title": row[1],
        "content": row[2],
        "domain": row[3],
        "timestamp": row[4],
        "embedding": np.frombuffer(row[5], dtype=np.float32) if row[5] else None,
    }


def get_url_cluster_map(user_id: str, urls: List[str]) -> Dict[str, Optional[str]]:
    if not urls:
        return {}
    normalized_urls = [normalize_url(u) for u in urls if u]
    if not normalized_urls:
        return {}
    placeholders = ",".join("?" for _ in normalized_urls)
    cursor.execute(
        f"SELECT url, cluster_id FROM articles WHERE user_id = ? AND url IN ({placeholders})",
        (user_id, *normalized_urls),
    )
    return {
        normalize_url(url): normalize_url(cluster_id) if cluster_id else None
        for url, cluster_id in cursor.fetchall()
    }


def get_cluster_members_for_cluster_ids(user_id: str, cluster_ids: List[str]) -> List[str]:
    normalized = [normalize_url(c) for c in cluster_ids if c]
    if not normalized:
        return []
    placeholders = ",".join("?" for _ in normalized)
    cursor.execute(
        f"SELECT url FROM articles WHERE user_id = ? AND cluster_id IN ({placeholders})",
        (user_id, *normalized),
    )
    return [normalize_url(url) for (url,) in cursor.fetchall() if url]


def set_cluster_for_urls(user_id: str, urls: List[str], cluster_id: str):
    normalized_urls = [normalize_url(u) for u in urls if u]
    if not normalized_urls:
        return
    placeholders = ",".join("?" for _ in normalized_urls)
    cursor.execute(
        f"UPDATE articles SET cluster_id = ? WHERE user_id = ? AND url IN ({placeholders})",
        (normalize_url(cluster_id), user_id, *normalized_urls),
    )
    conn.commit()


def update_similarity(user_id: str, url: str, similarity: Optional[float]):
    cursor.execute(
        "UPDATE articles SET similarity = ? WHERE user_id = ? AND url = ?",
        (similarity, user_id, normalize_url(url)),
    )
    conn.commit()


def assign_article_to_best_match_cluster(
    user_id: str,
    article_url: str,
    best_match_url: Optional[str],
    best_match_similarity: Optional[float],
) -> str:
    article_url = normalize_url(article_url)

    # no match — article becomes its own cluster
    if not best_match_url:
        set_cluster_for_urls(user_id, [article_url], article_url)
        update_similarity(user_id, article_url, None)
        return article_url

    best_match_url = normalize_url(best_match_url)
    url_cluster_map = get_url_cluster_map(user_id, [best_match_url])
    best_match_cluster_id = normalize_url(url_cluster_map.get(best_match_url) or "")

    print("[storage] assign_article_to_best_match_cluster", {
        "article_url": article_url,
        "best_match_url": best_match_url,
        "best_match_cluster_id": best_match_cluster_id,
        "best_match_similarity": best_match_similarity,
    })

    if best_match_cluster_id:
        # best match already belongs to a cluster — join it
        cluster_id = best_match_cluster_id
        set_cluster_for_urls(user_id, [article_url], cluster_id)
    else:
        # best match has no cluster yet — form a new one with best match as root
        cluster_id = best_match_url
        set_cluster_for_urls(user_id, [best_match_url, article_url], cluster_id)

    update_similarity(user_id, best_match_url, best_match_similarity)
    update_similarity(user_id, article_url, best_match_similarity)

    print("[storage] final_cluster_assignment", {"article_url": article_url, "cluster_id": cluster_id})
    return cluster_id


def get_content_by_urls(user_id: str, urls: list) -> dict:
    # returns {url: (title, content)} for novelty comparison
    if not urls:
        return {}
    result = {}
    for url in urls:
        cursor.execute(
            "SELECT title, content FROM articles WHERE user_id = ? AND url = ?",
            (user_id, normalize_url(url)),
        )
        row = cursor.fetchone()
        if row:
            result[normalize_url(url)] = (row[0], row[1])
    return result


def load_all(user_id: str):
    cursor.execute(
        "SELECT title, url, domain, timestamp, embedding FROM articles WHERE user_id = ?",
        (user_id,),
    )
    rows = cursor.fetchall()

    titles, urls, domains, timestamps, embs = [], [], [], [], []
    for t, u, d, ts, e in rows:
        titles.append(t)
        urls.append(u)
        domains.append(d or "")
        timestamps.append(ts or "")
        embs.append(np.frombuffer(e, dtype=np.float32))

    if not embs:
        return [], [], [], [], None
    return titles, urls, domains, timestamps, np.vstack(embs)


def get_embeddings_by_urls(user_id: str, urls: List[str]) -> List[np.ndarray]:
    if not urls:
        return []
    normalized_urls = [normalize_url(u) for u in urls if u]
    if not normalized_urls:
        return []
    placeholders = ",".join("?" for _ in normalized_urls)
    cursor.execute(
        f"SELECT embedding FROM articles WHERE user_id = ? AND url IN ({placeholders})",
        (user_id, *normalized_urls),
    )
    return [np.frombuffer(e, dtype=np.float32) for (e,) in cursor.fetchall() if e]