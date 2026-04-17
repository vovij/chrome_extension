"""Shared test helpers — imported by unit and integration test files."""

import numpy as np
from types import SimpleNamespace


def make_random_embedding(seed: int = 0, dim: int = 384) -> np.ndarray:
    """Unit-normalised random embedding, reproducible by seed."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def make_article(
    url: str = "https://example.com/article",
    title: str = "Test Article",
    content: str = "Some article content about technology.",
    domain: str = "example.com",
    timestamp: str = "2024-01-01T00:00:00Z",
) -> SimpleNamespace:
    """Return a minimal ArticleInput-like SimpleNamespace."""
    return SimpleNamespace(url=url, title=title, content=content, domain=domain, timestamp=timestamp)
