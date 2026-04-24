# utils.py
import os, json, random ,gzip
from pathlib import Path
from typing import Dict, List
import numpy as np
import orjson
import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score

from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from datetime import datetime
import collections


def set_seed(seed:int):
    random.seed(seed)
    np.random.seed(seed)

def read_jsonl(path:str):
    with open(path, "rb") as f:
        for line in f:
            if line.strip():
                yield orjson.loads(line)

def read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)

def write_json(path:str, obj:dict):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def write_jsonl(path:str, rows:List[dict]):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        for r in rows:
            f.write(orjson.dumps(r, option=orjson.OPT_SERIALIZE_NUMPY))
            f.write(b"\n")

def build_text(a:dict, clip_chars:int=2000, text_field:str=None) -> str:
    if text_field and text_field in a and a[text_field]:
        return a[text_field]
    title = a.get("title") or ""
    body  = a.get("text")  or a.get("content") or ""
    return f"{title}\n\n{body[:clip_chars]}"

def make_text(a:dict, strategy:str, lede_chars:int, clip_chars:int) -> str:
    title = a.get("title") or ""
    body  = a.get("text")  or a.get("content") or ""
    if strategy == "title":
        return title
    if strategy == "title+lede":
        return f"{title}\n\n{body[:lede_chars]}"
    # title+text_clip
    return f"{title}\n\n{body[:clip_chars]}"

def load_articles(path:str, clip_chars:int=2000, text_field:str=None) -> Dict[str,dict]:
    d = {}
    for r in read_jsonl(path):
        aid = r.get("id")
        if not aid: continue
        r["_text"] = build_text(r, clip_chars=clip_chars, text_field=text_field)
        d[aid] = r
    return d

def load_pairs(path:str) -> pd.DataFrame:
    return pd.DataFrame(list(read_jsonl(path)))

def load_encoder(model_name:str=None, model_dir:str=None, device:str=None) -> SentenceTransformer:
    if model_dir:
        print(f"[model] loading from dir: {model_dir}")
        return SentenceTransformer(model_dir, device=device or "cuda")
    if model_name:
        print(f"[model] loading hub: {model_name}")
        return SentenceTransformer(model_name, device=device or "cuda")
    raise ValueError("Provide model_name or model_dir")

def encode_id_texts(model:SentenceTransformer, id2a:Dict[str,dict], batch_size:int=128) -> Dict[str,np.ndarray]:
    ids = list(id2a.keys())
    texts = [id2a[i]["_text"] for i in ids]
    vecs = model.encode(texts, batch_size=batch_size, convert_to_numpy=True,
                        normalize_embeddings=True, show_progress_bar=True).astype(np.float32)
    return {ids[i]: vecs[i] for i in range(len(ids))}

def fill_E(df_pairs:pd.DataFrame, id2emb:Dict[str,np.ndarray]) -> pd.DataFrame:
    E, miss = [], 0
    for _, row in df_pairs.iterrows():
        v1 = id2emb.get(row["id1"]); v2 = id2emb.get(row["id2"])
        if v1 is None or v2 is None: E.append(np.nan); miss += 1
        else: E.append(float(np.dot(v1, v2)))
    if miss: print(f"[warn] missing embeddings: {miss}")
    df = df_pairs.copy(); df["E"] = E
    return df.dropna(subset=["E"])

def pick_tau_for_precision(y_true:np.ndarray, scores:np.ndarray, target_precision=0.95):
    cand = np.linspace(0.0, 1.0, 1001)
    best = {"tau":0.5,"precision":0.0,"recall":0.0,"f1":0.0}
    for t in cand:
        y_pred = (scores >= t).astype(int)
        p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
        if p + 1e-9 >= target_precision and r > best["recall"]:
            best = {"tau": float(t), "precision": float(p), "recall": float(r), "f1": float(f1)}
    if best["precision"] < target_precision:
        f1best, tau = 0.0, 0.5
        for t in cand:
            y_pred = (scores >= t).astype(int)
            p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
            if f1 > f1best: f1best, tau = f1, t
        y_pred = (scores >= tau).astype(int)
        p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
        best = {"tau": float(tau), "precision": float(p), "recall": float(r), "f1": float(f1)}
    return best

def eval_with_fixed_tau(y_true:np.ndarray, scores:np.ndarray, tau:float):
    y_pred = (scores >= tau).astype(int)
    p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    auc = roc_auc_score(y_true, scores)
    return {"precision": float(p), "recall": float(r), "f1": float(f1), "auc": float(auc)}

def train_logreg(train_df:pd.DataFrame, val_df:pd.DataFrame, feature_cols:List[str], target_precision=0.95):
    X_tr = train_df[feature_cols].values.astype(np.float32); y_tr = train_df["label"].values.astype(int)
    X_va = val_df[feature_cols].values.astype(np.float32);   y_va = val_df["label"].values.astype(int)
    clf = LogisticRegression(max_iter=1000, class_weight="balanced"); clf.fit(X_tr, y_tr)
    va_scores = clf.predict_proba(X_va)[:, 1]
    best = pick_tau_for_precision(y_va, va_scores, target_precision)
    return clf, best

def eval_logreg(df:pd.DataFrame, feature_cols:List[str], clf:LogisticRegression, tau_prob:float):
    X = df[feature_cols].values.astype(np.float32); y = df["label"].values.astype(int)
    prob = clf.predict_proba(X)[:, 1]
    y_pred = (prob >= tau_prob).astype(int)
    p, r, f1, _ = precision_recall_fscore_support(y, y_pred, average="binary", zero_division=0)
    auc = roc_auc_score(y, prob)
    return {"precision": float(p), "recall": float(r), "f1": float(f1), "auc": float(auc)}

def parse_time_iso(ts):
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except Exception:
        return None
    
def normalize_url(url):
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower()
        if host.startswith("m."):
            host = host[2:]
        # strip trackers
        qs = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
              if not (k.startswith("utm_") or k in {"gclid", "fbclid"})]
        # sort for stability
        qs = sorted(qs, key=lambda kv: kv[0])
        # normalize path
        path = (u.path or "").rstrip("/")
        if path.endswith("/amp"):
            path = path[:-4]
        return urlunparse((u.scheme, host, path, u.params, urlencode(qs), u.fragment))
    except Exception:
        return url
    
def extract_domain(url):
    try:
        return (urlparse(url).hostname or "").lower()
    except:
        return ""
    
def tokenize_title(t):
    if not t: return []
    t = t.lower()
    buf = []
    for ch in t:
        buf.append(ch if (ch.isalnum() or ch.isspace()) else " ")
    toks = [tok for tok in "".join(buf).split() if len(tok) > 1]
    return toks

def hash32(s):
    h = 2166136261
    for c in s.encode("utf-8", errors="ignore"):
        h ^= c
        h = (h * 16777619) & 0xFFFFFFFF
    return h

def hash64(s):
    a = hash32(s)
    b = hash32(s + "#")
    return (a << 32) | b

def simhash64_from_text(text):
    toks = tokenize_title(text)
    if not toks:
        return 0
    weights = collections.Counter(toks)  # simple TF
    bits = [0] * 64
    for tok, w in weights.items():
        hv = hash64(tok)
        for i in range(64):
            if (hv >> i) & 1:
                bits[i] += w
            else:
                bits[i] -= w
    out = 0
    for i in range(64):
        if bits[i] > 0:
            out |= (1 << i)
    return out

def hamming64(a, b):
    x = a ^ b
    cnt = 0
    while x:
        cnt += x & 1
        x >>= 1
    return cnt

def jaccard(a_tokens, b_tokens):
    A, B = set(a_tokens), set(b_tokens)
    if not A and not B:
        return 0.0
    return len(A & B) / max(1, len(A | B))

def pick_threshold_for_precision(y_true, scores, target_precision=0.95):
    cand = np.linspace(0.0, 1.0, 1001)
    best = {"tau":0.5,"precision":0.0,"recall":0.0,"f1":0.0}
    for t in cand:
        y_pred = (scores >= t).astype(int)
        p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
        if p + 1e-9 >= target_precision and r > best["recall"]:
            best = {"tau":float(t), "precision":float(p), "recall":float(r), "f1":float(f1)}
    if best["precision"] < target_precision:
        # fallback to best F1
        f1best, tau = 0.0, 0.5
        for t in cand:
            y_pred = (scores >= t).astype(int)
            p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
            if f1 > f1best:
                f1best, tau = f1, t
        y_pred = (scores >= tau).astype(int)
        p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
        best = {"tau":float(tau), "precision":float(p), "recall":float(r), "f1":float(f1)}
    return best