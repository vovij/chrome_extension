# Benchmark version of post-train_MiniLM.py
# Runs multiple pretrained embedding models and produces a comparison table
# Tests E5 and BGE models with correct instruction prefixes

import os, json, random, time
from pathlib import Path
from typing import Dict
import orjson
import numpy as np
import pandas as pd
from tqdm import tqdm
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score
from sentence_transformers import SentenceTransformer
import torch

# =========================
# Models to compare
# =========================
MODEL_LIST = [
    "sentence-transformers/all-MiniLM-L6-v2",
    "sentence-transformers/all-MiniLM-L12-v2",
    "sentence-transformers/all-mpnet-base-v2",
    "intfloat/e5-base-v2",
    "BAAI/bge-base-en-v1.5",
]

# =========================
# Configurable Parameters
# =========================
CONFIG = {
    "articles_train": "out_wcep_posttrain/articles.train.jsonl",
    "articles_val":   "out_wcep_posttrain/articles.val.jsonl",
    "articles_test":  "out_wcep_posttrain/articles.test.jsonl",
    "pairs_train":    "out_wcep_posttrain/pairs.train.jsonl",
    "pairs_val":      "out_wcep_posttrain/pairs.val.jsonl",
    "pairs_test":     "out_wcep_posttrain/pairs.test.jsonl",

    "outdir": "out_embedding_benchmark",
    "seed": 2026,
    "device": None,

    "batch_size": 64,
    "max_text_len": 2000,
    "target_precision": 0.95,
}

# =========================
# Utilities
# =========================

def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def read_jsonl(path: str):
    with open(path, "rb") as f:
        for line in f:
            if line.strip():
                yield orjson.loads(line)


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


# =========================
# Model-specific formatting
# =========================

def format_text_for_model(model_name: str, text: str) -> str:
    if "intfloat/e5" in model_name:
        return "passage: " + text
    if "BAAI/bge" in model_name:
        return "Represent this sentence for semantic similarity: " + text
    return text


# =========================
# Model and Embeddings
# =========================

def load_model(model_name: str):
    device = CONFIG["device"] or ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[model] loading {model_name} on {device}")
    return SentenceTransformer(model_name, device=device)


def batch_encode_texts(model, texts):
    return model.encode(
        texts,
        batch_size=CONFIG["batch_size"],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True
    ).astype(np.float32)


# =========================
# Data Loading
# =========================

def load_articles(path: str) -> Dict[str, dict]:
    return {r["id"]: r for r in read_jsonl(path)}


def load_pairs(path: str) -> pd.DataFrame:
    return pd.DataFrame(list(read_jsonl(path)))


# =========================
# Embedding + Similarity
# =========================

def build_id_embeddings(articles, model, model_name):
    ids, texts = [], []

    for aid, a in articles.items():
        title = a.get("title") or ""
        text = a.get("text") or a.get("content") or ""
        raw = title + "\n\n" + text[:CONFIG["max_text_len"]]
        formatted = format_text_for_model(model_name, raw)

        ids.append(aid)
        texts.append(formatted)

    vecs = batch_encode_texts(model, texts)
    return {aid: vecs[i] for i, aid in enumerate(ids)}


def fill_pairs_with_E(df_pairs, id2emb):
    E = []
    for _, row in df_pairs.iterrows():
        v1 = id2emb[row["id1"]]
        v2 = id2emb[row["id2"]]
        E.append(cosine_sim(v1, v2))

    df = df_pairs.copy()
    df["E"] = E
    return df


# =========================
# Evaluation helpers
# =========================

def pick_threshold_for_precision(y_true, scores, target_precision):
    cand = np.linspace(0, 1, 1001)
    best = {"tau": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0}

    for t in cand:
        y_pred = (scores >= t).astype(int)
        p, r, f1, _ = precision_recall_fscore_support(
            y_true, y_pred, average="binary", zero_division=0
        )
        if p >= target_precision and r > best["recall"]:
            best = {"tau": float(t), "precision": float(p), "recall": float(r), "f1": float(f1)}

    return best


# =========================
# Run one model
# =========================

def run_model(model_name):
    set_seed(CONFIG["seed"])
    model = load_model(model_name)

    arts_tr = load_articles(CONFIG["articles_train"])
    arts_va = load_articles(CONFIG["articles_val"])
    arts_te = load_articles(CONFIG["articles_test"])
    pairs_va = load_pairs(CONFIG["pairs_val"])
    pairs_te = load_pairs(CONFIG["pairs_test"])

    t0 = time.time()
    emb_tr = build_id_embeddings(arts_tr, model, model_name)
    emb_va = build_id_embeddings(arts_va, model, model_name)
    emb_te = build_id_embeddings(arts_te, model, model_name)
    encode_time = time.time() - t0

    pairs_va = fill_pairs_with_E(pairs_va, emb_va)
    pairs_te = fill_pairs_with_E(pairs_te, emb_te)

    best = pick_threshold_for_precision(
        pairs_va["label"].values,
        pairs_va["E"].values,
        CONFIG["target_precision"]
    )

    y_test = pairs_te["label"].values
    scores = pairs_te["E"].values
    y_pred = (scores >= best["tau"]).astype(int)

    p, r, f1, _ = precision_recall_fscore_support(
        y_test, y_pred, average="binary", zero_division=0
    )
    auc = roc_auc_score(y_test, scores)

    return {
        "model": model_name,
        "embed_dim": next(iter(emb_tr.values())).shape[0],
        "tau_val": best["tau"],
        "test_precision": float(p),
        "test_recall": float(r),
        "test_f1": float(f1),
        "test_auc": float(auc),
        "encode_time_s": round(encode_time, 2),
    }


# =========================
# Main benchmark loop
# =========================

def main():
    Path(CONFIG["outdir"]).mkdir(exist_ok=True)
    rows = []

    for m in MODEL_LIST:
        print("\n==============================")
        print("Running", m)
        rows.append(run_model(m))

    df = pd.DataFrame(rows).sort_values(by="test_recall", ascending=False)
    out_path = os.path.join(CONFIG["outdir"], "embedding_comparison.csv")
    df.to_csv(out_path, index=False)

    print("\n=== Embedding Comparison ===")
    print(df)
    print("\nSaved to:", out_path)


if __name__ == "__main__":
    main()
