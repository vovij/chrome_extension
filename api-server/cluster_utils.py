import numpy as np
from typing import List, Sequence, Union


def compute_centroid(embeddings: List[List[float]]) -> List[float]:
    """
    Average embedding of a cluster.
    """
    if not embeddings:
        return []

    arr = np.array(embeddings, dtype=float)
    centroid = arr.mean(axis=0)
    return centroid.tolist()


ArrayLike = Union[Sequence[float], np.ndarray]

def cosine_similarity(a: ArrayLike, b: ArrayLike) -> float:
    if a is None or b is None:
        return 0.0

    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)

    if a.size == 0 or b.size == 0:
        return 0.0

    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0

    return float(np.dot(a, b) / denom)


def compute_novelty_score(new_embedding, centroid_embedding) -> float:
    """
    Novelty = distance from cluster center.
    """
    sim = cosine_similarity(new_embedding, centroid_embedding)

    # Convert similarity to novelty
    novelty = 1.0 - sim

    # Clamp for safety
    return max(0.0, min(1.0, novelty))
