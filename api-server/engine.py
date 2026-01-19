import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingEngine:
    def __init__(self):
        self.model = SentenceTransformer(MODEL_NAME)

    def embed(self, title: str, content: str) -> np.ndarray:
        text = title + "\n\n" + content[:2000]
        emb = self.model.encode(text, normalize_embeddings=True)
        return emb.astype(np.float32)

    @staticmethod
    def cosine(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))
