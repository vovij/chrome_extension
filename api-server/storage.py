import sqlite3
import numpy as np
from typing import List, Optional, Dict, Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# Basic URL normalization to prevent duplicates for the same page.
# - lowercases scheme/host
# - strips leading www.
# - removes fragments (#...)
# - drops common tracking query params (utm_*, ref, cmpid, ocid, taid, rpc)
# - trims trailing slash (except "/")
TRACKING_KEYS_PREFIX = ("utm_",)
DROP_QUERY_KEYS = {"ref", "cmpid", "ocid", "taid", "rpc"}


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

    # remove fragments
    fragment = ""

    # remove tracking params
    q = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        kl = k.lower()
        if kl.startswith(TRACKING_KEYS_PREFIX):
            continue
        if kl in DROP_QUERY_KEYS:
            continue
        q.append((k, v))
    query = urlencode(q, doseq=True)

    return urlunsplit((scheme, netloc, path, query, fragment))


conn = sqlite3.connect("articles.db", check_same_thread=False)
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
    INSERT OR IGNORE INTO articles
    (user_id, url, title, content, domain, timestamp, embedding, cluster_id, similarity)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        article.url,
        article.title,
        article.content,
        article.domain,
        article.timestamp,
        embedding.tobytes(),
        cluster_id,
        similarity
    ))
    conn.commit()


def get_article_by_url(url: str, user_id: str) -> Optional[dict]:
    """Get article by URL if it exists"""
    cursor.execute(
        "SELECT url, title, content, domain, timestamp, embedding FROM articles WHERE url = ? AND user_id = ?",
        (normalize_url(url), user_id)
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
        "embedding": np.frombuffer(row[5], dtype=np.float32) if row[5] else None
    }


def load_all(user_id: str):
    cursor.execute(
        "SELECT title, url, domain, timestamp, embedding FROM articles WHERE user_id = ?",
        (user_id,)
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


def get_embeddings_by_urls(urls: List[str]) -> List[np.ndarray]:
    """
    Return embeddings for a set of URLs (used to compute centroid).
    """
    if not urls:
        return []

    placeholders = ",".join("?" for _ in urls)
    cursor.execute(
        f"SELECT embedding FROM articles WHERE url IN ({placeholders})",
        urls
    )
    rows = cursor.fetchall()

    out: List[np.ndarray] = []
    for (e,) in rows:
        if e:
            out.append(np.frombuffer(e, dtype=np.float32))
    return out
