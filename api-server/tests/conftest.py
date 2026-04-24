"""
Shared pytest configuration and stubs for the SeenIt test suite.

Runs automatically before any test file is collected. Responsible for:
  - Stubbing heavy dependencies so tests run fast without a real ML model or DB connection
  - Providing the isolated_storage fixture used by storage and integration tests
"""

import sys
import types
import sqlite3

import numpy as np
import pytest

# Project helpers
from helpers import make_article, make_random_embedding 
import storage as _storage_mod



# Stub: sentence_transformers
#
# The real model is ~90 MB and takes several seconds to load.
# This fake returns a deterministic random vector for any input text,
# keeping tests fast and reproducible without sacrificing correctness.


_st_stub = types.ModuleType("sentence_transformers")


class _FakeSentenceTransformer:
    def __init__(self, name: str) -> None:
        pass

    def encode(self, text: str, normalize_embeddings: bool = False) -> np.ndarray:
        rng = np.random.default_rng(abs(hash(text)) % (2 ** 31))
        v = rng.standard_normal(384).astype(np.float32)
        if normalize_embeddings:
            v /= np.linalg.norm(v)
        return v


_st_stub.SentenceTransformer = _FakeSentenceTransformer
sys.modules.setdefault("sentence_transformers", _st_stub)



# Stub: FastAPI-Users, SQLAlchemy, aiosqlite, dotenv
#
# These libraries connect to a real database and set up async engines at
# import time. Replacing them with empty modules lets us import app-level
# code (storage.py, auth.py, etc.) without spinning up any infrastructure.

_STUB_MODULES = [
    "fastapi_users",
    "fastapi_users.authentication",
    "fastapi_users.authentication.backend",
    "fastapi_users.authentication.transport",
    "fastapi_users.authentication.transport.bearer",
    "fastapi_users.authentication.strategy",
    "fastapi_users.authentication.strategy.jwt",
    "fastapi_users.db",
    "fastapi_users.exceptions",
    "fastapi_users.schemas",
    "sqlalchemy",
    "sqlalchemy.ext",
    "sqlalchemy.ext.asyncio",
    "sqlalchemy.orm",
    "aiosqlite",
    "dotenv",
]

for _mod_name in _STUB_MODULES:
    sys.modules.setdefault(_mod_name, types.ModuleType(_mod_name))

# Prevent load_dotenv() from touching the filesystem during tests
sys.modules["dotenv"].load_dotenv = lambda *a, **kw: None  # type: ignore[attr-defined]



# Stub: optional content-extraction libraries
#
# trafilatura, readability, and bs4 are only needed for the /extract-url
# endpoint. They may not be installed in all environments, so we stub them
# to avoid ImportErrors in unrelated tests.


for _mod_name in ["trafilatura", "readability", "bs4"]:
    sys.modules.setdefault(_mod_name, types.ModuleType(_mod_name))



# Fixture: isolated_storage
#
# Any test that reads or writes to the database should request this fixture.
# It redirects storage.py's global `conn` and `cursor` to a fresh in-memory
# SQLite file inside pytest's tmp_path, so the real articles.db is never
# touched and tests never interfere with each other.


@pytest.fixture()
def isolated_storage(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_articles.db")
    new_conn = sqlite3.connect(db_path, check_same_thread=False)
    new_cursor = new_conn.cursor()

    new_cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL,
            cluster_id  TEXT,
            similarity  REAL,
            url         TEXT,
            title       TEXT,
            content     TEXT,
            domain      TEXT,
            timestamp   TEXT,
            embedding   BLOB,
            simhash64   TEXT,      
            title_tokens TEXT,    
            UNIQUE(user_id, url)
        )
    """)
    new_conn.commit()

    # Patch the module-level connection used by all storage functions
    monkeypatch.setattr(_storage_mod, "conn",   new_conn)
    monkeypatch.setattr(_storage_mod, "cursor", new_cursor)

    yield new_conn, new_cursor

    new_conn.close()