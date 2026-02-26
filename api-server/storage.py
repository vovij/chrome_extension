import sqlite3
import numpy as np
from typing import List, Optional, Dict, Any

conn = sqlite3.connect("articles.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    url TEXT UNIQUE,
    title TEXT,
    content TEXT,
    domain TEXT,
    timestamp TEXT,
    embedding BLOB,
    UNIQUE(user_id, url)
)
""")
conn.commit()


def save_article(article, embedding: np.ndarray, user_id: str):
    cursor.execute("""
    INSERT OR IGNORE INTO articles
    (user_id, url, title, content, domain, timestamp, embedding)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        article.url,
        article.title,
        article.content,
        article.domain,
        article.timestamp,
        embedding.tobytes()
    ))
    conn.commit()


def get_article_by_url(url: str, user_id: str) -> Optional[dict]:
    """Get article by URL if it exists"""
    cursor.execute(
        "SELECT url, title, content, domain, timestamp, embedding FROM articles WHERE url = ? AND user_id = ?",
        (url, user_id)
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


def load_all():
    cursor.execute("SELECT title, url, domain, timestamp, embedding FROM articles WHERE user_id = ?")
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
