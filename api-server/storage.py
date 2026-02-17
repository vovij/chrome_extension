import sqlite3
import numpy as np

conn = sqlite3.connect("articles.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE,
    title TEXT,
    content TEXT,
    domain TEXT,
    timestamp TEXT,
    embedding BLOB
)
""")
conn.commit()


def save_article(article, embedding: np.ndarray):
    cursor.execute("""
    INSERT OR IGNORE INTO articles
    (url, title, content, domain, timestamp, embedding)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        article.url,
        article.title,
        article.content,
        article.domain,
        article.timestamp,
        embedding.tobytes()
    ))
    conn.commit()


def get_article_by_url(url: str):
    """Get article by URL if it exists"""
    cursor.execute("SELECT url, title, embedding FROM articles WHERE url = ?", (url,))
    row = cursor.fetchone()
    
    if row:
        return {
            'url': row[0],
            'title': row[1],
            'embedding': np.frombuffer(row[2], dtype=np.float32)
        }
    return None


def load_all():
    cursor.execute("SELECT title, url, embedding FROM articles")
    rows = cursor.fetchall()

    titles, urls, embs = [], [], []
    for t, u, e in rows:
        titles.append(t)
        urls.append(u)
        embs.append(np.frombuffer(e, dtype=np.float32))

    if not embs:
        return [], [], None

    return titles, urls, np.vstack(embs)