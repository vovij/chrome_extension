import os
import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = os.getenv("SEENIT_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# To run the backend for a particular model, use:
# SEENIT_MODEL="your_model_name" uvicorn app:app --reload --port 8000

class EmbeddingEngine:
    def __init__(self):
        print(f"[engine] loading embedding model: {MODEL_NAME}")
        self.model = SentenceTransformer(MODEL_NAME)

    def _format_text(self, model_name: str, text: str) -> str:
        if "intfloat/e5" in model_name:
            return "passage: " + text
        if "BAAI/bge" in model_name:
            return "Represent this sentence for semantic similarity: " + text
        return text

    def embed(self, title: str, content: str) -> np.ndarray:
        content = content or ""
        head = content[:1600]
        tail = content[-400:] if len(content) > 2000 else ""
        text = title + "\n\n" + head + ("\n\n" + tail if tail else "")
        text = self._format_text(MODEL_NAME, text)
        emb = self.model.encode(text, normalize_embeddings=True)
        return emb.astype(np.float32)

    @staticmethod
    def cosine(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))
