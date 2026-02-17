import sqlite3
import numpy as np
from typing import Optional

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
        "SELECT url, title, embedding FROM articles WHERE url = ? AND user_id = ?",
        (url, user_id)
    )
    row = cursor.fetchone()
    
    if row:
        return {
            'url': row[0],
            'title': row[1],
            'embedding': np.frombuffer(row[2], dtype=np.float32)
        }
    return None


def load_all(user_id: str):
    """Load all articles for specific user"""
    cursor.execute(
        "SELECT title, url, embedding FROM articles WHERE user_id = ?",
        (user_id,)
    )
    rows = cursor.fetchall()

    titles, urls, embs = [], [], []
    for t, u, e in rows:
        titles.append(t)
        urls.append(u)
        embs.append(np.frombuffer(e, dtype=np.float32))

    if not embs:
        return [], [], None

    return titles, urls, np.vstack(embs)