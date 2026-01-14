import os, json, math, random
from pathlib import Path
from typing import Dict, List
import orjson
import numpy as np
import pandas as pd
from tqdm import tqdm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score
from sentence_transformers import SentenceTransformer
import torch

# =========================
# Configurable Parameters (Modify here directly)
# =========================
CONFIG = {
    # Data paths (use the WCEP derived files generated in the previous step)
    "articles_train": "out_wcep_posttrain/articles.train.jsonl",
    "articles_val":   "out_wcep_posttrain/articles.val.jsonl",
    "articles_test":  "out_wcep_posttrain/articles.test.jsonl",
    "pairs_train":    "out_wcep_posttrain/pairs.train.jsonl",
    "pairs_val":      "out_wcep_posttrain/pairs.val.jsonl",
    "pairs_test":     "out_wcep_posttrain/pairs.test.jsonl",

    # Output directory
    "outdir": "out_posttrain_minilm",

    # Random seed and device
    "seed": 2026,
    "device": None,  # "cuda" / "cpu" / None(auto)

    # Model and inference
    "model_name": "sentence-transformers/all-MiniLM-L6-v2",
    "batch_size": 64,
    "text_strategy": "title+text",  # "title+text" or "title"
    "max_text_len": 2000,

    # Target precision (for threshold selection)
    "target_precision": 0.95,

    # Whether to save intermediate pairs with E
    "save_pairs_with_E": True,
}

# =========================
# Utility Functions
# =========================
def set_seed(seed: int = 2026):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

def read_jsonl(path: str):
    with open(path, "rb") as f:
        for line in f:
            if not line.strip():
                continue
            yield orjson.loads(line)

def write_jsonl(path: str, rows: List[dict]):
    with open(path, "wb") as f:
        for r in rows:
            f.write(orjson.dumps(r, option=orjson.OPT_SERIALIZE_NUMPY))
            f.write(b"\n")

def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / ((np.linalg.norm(a) + 1e-9) * (np.linalg.norm(b) + 1e-9)))

# =========================
# Model and Embeddings
# =========================
def load_model(model_name: str, device: str = None):
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[model] loading {model_name} on {device}")
    model = SentenceTransformer(model_name, device=device)
    return model, device

def batch_encode_texts(model: SentenceTransformer, texts: List[str], batch_size: int = 64, show_progress: bool = True):
    vecs = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,  # L2 normalization already done
        show_progress_bar=show_progress
    )
    return vecs.astype(np.float32)

# =========================
# Data Loading
# =========================
def load_articles(articles_path: str) -> Dict[str, dict]:
    d = {}
    for r in read_jsonl(articles_path):
        aid = r.get("id")
        if not aid:
            continue
        d[aid] = r
    print(f"[load] articles: {len(d)} from {articles_path}")
    return d

def load_pairs(pairs_path: str) -> pd.DataFrame:
    rows = []
    for r in read_jsonl(pairs_path):
        rows.append(r)
    df = pd.DataFrame(rows)
    print(f"[load] pairs: {len(df)} from {pairs_path}")
    return df

# =========================
# Calculate E (Cosine Similarity)
# =========================
def build_id_embeddings(articles: Dict[str, dict],
                        model: SentenceTransformer,
                        text_strategy: str = "title+text",
                        max_text_len: int = 2000,
                        batch_size: int = 64) -> Dict[str, np.ndarray]:
    ids, texts = [], []
    for aid, a in articles.items():
        title = a.get("title") or ""
        text = a.get("text") or a.get("content") or ""
        if text_strategy == "title":
            merged = title
        else:
            merged = (title + "\n\n" + text[:max_text_len])
        ids.append(aid)
        texts.append(merged)

    vecs = batch_encode_texts(model, texts, batch_size=batch_size, show_progress=True)
    emb = {aid: vecs[i] for i, aid in enumerate(ids)}
    return emb

def fill_pairs_with_E(df_pairs: pd.DataFrame, id2emb: Dict[str, np.ndarray]) -> pd.DataFrame:
    E = []
    missing = 0
    for _, row in df_pairs.iterrows():
        v1 = id2emb.get(row["id1"])
        v2 = id2emb.get(row["id2"])
        if v1 is None or v2 is None:
            E.append(np.nan)
            missing += 1
        else:
            E.append(cosine_sim(v1, v2))
    if missing:
        print(f"[warn] pairs missing embeddings: {missing}")
    df_pairs = df_pairs.copy()
    df_pairs["E"] = E
    return df_pairs.dropna(subset=["E"])

# =========================
# Threshold/Weight Learning
# =========================
def pick_threshold_for_precision(y_true, scores, target_precision=0.95):
    # Scan threshold between 0..1, select threshold with highest recall when target precision is reached
    cand = np.linspace(0.0, 1.0, 1001)
    best = {"tau": 0.5, "precision": 0.0, "recall": 0.0, "f1": 0.0}
    for t in cand:
        y_pred = (scores >= t).astype(int)
        p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
        if p + 1e-9 >= target_precision:
            if r > best["recall"]:
                best = {"tau": float(t), "precision": float(p), "recall": float(r), "f1": float(f1)}
    # If target precision is not reached, fallback to highest F1
    if best["precision"] < target_precision:
        f1best, best_t = 0.0, 0.5
        for t in cand:
            y_pred = (scores >= t).astype(int)
            p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
            if f1 > f1best:
                f1best, best_t = f1, t
        y_pred = (scores >= best_t).astype(int)
        p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
        best = {"tau": float(best_t), "precision": float(p), "recall": float(r), "f1": float(f1)}
    return best

def train_logreg(train_df: pd.DataFrame, val_df: pd.DataFrame, feature_cols: List[str], target_precision=0.95):
    X_tr = train_df[feature_cols].values.astype(np.float32)
    y_tr = train_df["label"].values.astype(int)
    X_va = val_df[feature_cols].values.astype(np.float32)
    y_va = val_df["label"].values.astype(int)

    clf = LogisticRegression(max_iter=1000, class_weight="balanced")
    clf.fit(X_tr, y_tr)

    va_scores = clf.predict_proba(X_va)[:, 1]
    best = pick_threshold_for_precision(y_va, va_scores, target_precision=target_precision)
    return clf, best, va_scores

def eval_on(df: pd.DataFrame, feature_cols: List[str], clf: LogisticRegression, tau_prob: float):
    X = df[feature_cols].values.astype(np.float32)
    y = df["label"].values.astype(int)
    prob = clf.predict_proba(X)[:, 1]
    y_pred = (prob >= tau_prob).astype(int)
    p, r, f1, _ = precision_recall_fscore_support(y, y_pred, average="binary", zero_division=0)
    auc = roc_auc_score(y, prob)
    return {"precision": float(p), "recall": float(r), "f1": float(f1), "auc": float(auc)}

# =========================
# Main Process
# =========================
def main():
    C = CONFIG
    set_seed(C["seed"])
    Path(C["outdir"]).mkdir(parents=True, exist_ok=True)

    # 1) Load model
    model, device = load_model(C["model_name"], device=C["device"])

    # 2) Read data
    arts_tr = load_articles(C["articles_train"])
    arts_va = load_articles(C["articles_val"])
    arts_te = load_articles(C["articles_test"])
    pairs_tr = load_pairs(C["pairs_train"])
    pairs_va = load_pairs(C["pairs_val"])
    pairs_te = load_pairs(C["pairs_test"])

    # 3) Calculate embeddings (calculate separately by split to avoid leakage)
    emb_tr = build_id_embeddings(arts_tr, model, C["text_strategy"], C["max_text_len"], C["batch_size"])
    emb_va = build_id_embeddings(arts_va, model, C["text_strategy"], C["max_text_len"], C["batch_size"])
    emb_te = build_id_embeddings(arts_te, model, C["text_strategy"], C["max_text_len"], C["batch_size"])

    # 4) Backfill E
    pairs_tr = fill_pairs_with_E(pairs_tr, emb_tr)
    pairs_va = fill_pairs_with_E(pairs_va, emb_va)
    pairs_te = fill_pairs_with_E(pairs_te, emb_te)

    # 5) Baseline (E threshold only)
    base_val = pick_threshold_for_precision(pairs_va["label"].values, pairs_va["E"].values, C["target_precision"])
    base_test_pred = (pairs_te["E"].values >= base_val["tau"]).astype(int)
    bp, br, bf1, _ = precision_recall_fscore_support(pairs_te["label"].values, base_test_pred, average="binary", zero_division=0)
    base_report = {
        "tau_embed": base_val["tau"],
        "val_metrics": base_val,
        "test_metrics": {"precision": float(bp), "recall": float(br), "f1": float(bf1)}
    }

    # 6) Combined features (Logistic Regression)
    feature_cols = [c for c in ["U","T","Sh","E","domain_same","time_diff_days"] if c in pairs_tr.columns]
    clf, best, _ = train_logreg(pairs_tr, pairs_va, feature_cols, C["target_precision"])
    logreg_test = eval_on(pairs_te, feature_cols, clf, best["tau"])

    # 7) Export config
    cfg = {
        "model_name": C["model_name"],
        "text_strategy": C["text_strategy"],
        "max_text_len": C["max_text_len"],
        "post_train": {
            "feature_cols": feature_cols,
            "logreg": {
                "weights": clf.coef_[0].tolist(),
                "bias": float(clf.intercept_[0]),
                "tau_prob": best["tau"]
            },
            "tau_embed_only": base_report["tau_embed"]
        },
        "metrics": {
            "embed_only": base_report,
            "logreg": {
                "val": best,
                "test": logreg_test
            }
        },
        "seed": C["seed"]
    }
    with open(os.path.join(C["outdir"], "post_train_config.minilm.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    if C.get("save_pairs_with_E", True):
        write_jsonl(os.path.join(C["outdir"], "pairs.train.withE.jsonl"), pairs_tr.to_dict(orient="records"))
        write_jsonl(os.path.join(C["outdir"], "pairs.val.withE.jsonl"),   pairs_va.to_dict(orient="records"))
        write_jsonl(os.path.join(C["outdir"], "pairs.test.withE.jsonl"),  pairs_te.to_dict(orient="records"))

    print("[done] config saved to", os.path.join(C["outdir"], "post_train_config.minilm.json"))
    print("[metrics] E-only (test):", base_report["test_metrics"])
    print("[metrics] logreg (test):", logreg_test)

if __name__ == "__main__":
    main()