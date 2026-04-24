import os, math, random, orjson, numpy as np
from pathlib import Path
from typing import List, Dict, Tuple
from collections import defaultdict, deque
from tqdm import tqdm
from sentence_transformers import SentenceTransformer, InputExample, losses
from torch.utils.data import DataLoader, Dataset
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score
from utils import *

# =========================
# CONFIG (edit here)
# =========================
CONFIG = {
    # Paths (built by your previous pipeline)
    "BASE_DIR": "out_wcep_dataset",                     # where articles/pairs live
    "ARTICLES_TRAIN": "out_wcep_dataset/articles.train.jsonl",
    "ARTICLES_VAL":   "out_wcep_dataset/articles.val.jsonl",
    "ARTICLES_TEST":  "out_wcep_dataset/articles.test.jsonl",
    "SFT_PAIRS_TRAIN":"out_wcep_dataset/sft_pairs.train.jsonl",  # positives only
    "VAL_PAIRS":      "out_wcep_dataset/pairs.val.jsonl",        # for eval
    "TEST_PAIRS":     "out_wcep_dataset/pairs.test.jsonl",       # for eval
    "OUT_DIR":        "out_sft_minilm_L12",

    # Model & training
    "MODEL_NAME": 'sentence-transformers/all-MiniLM-L12-v2', #"sentence-transformers/all-MiniLM-L6-v2",
    "DEVICE": 'cuda',               # None -> auto; or "cuda"/"cpu"
    "MAX_SEQ_LEN": 256,           # cap tokens (title+lede recommended)
    "BATCH_SIZE": 64,            #128 reduce if OOM
    "EPOCHS": 2,
    "USE_AMP": True,              # mixed precision for speed/memory
    "SEED": 2026,

    # Text building for training/eval
    "TEXT_STRATEGY": "title+lede",  # "title" | "title+lede" | "title+text_clip"
    "LEDE_CHARS": 512,              # for title+lede
    "TEXT_CLIP_CHARS": 2000,        # for title+text_clip

    # Eval: pick threshold to hit target precision, then report recall/F1
    "TARGET_PRECISION": 0.98
}


# =========================
# Data loading
# =========================
def load_articles(path:str, cfg) -> Dict[str, dict]:
    id2a = {}
    for r in read_jsonl(path):
        aid = r.get("id")
        if not aid: continue
        id2a[aid] = r
    # prepare text cache
    for aid, a in id2a.items():
        a["_text"] = make_text(a, cfg["TEXT_STRATEGY"], cfg["LEDE_CHARS"], cfg["TEXT_CLIP_CHARS"])
    return id2a

def load_sft_pairs(path:str) -> List[dict]:
    # Expect label==1 positives only; if your file contains label==0, filter them out
    rows = [r for r in read_jsonl(path) if int(r.get("label",1)) == 1]
    return rows

def load_eval_pairs(path:str) -> List[dict]:
    # For val/test evaluation, use both positives and negatives
    return list(read_jsonl(path))

# =========================
# Batch scheduling: ensure at most one pair per cluster per batch
# =========================
def build_event_disjoint_order(pairs:List[dict], batch_size:int) -> List[Tuple[dict,str]]:
    """
    Reorder pairs so that within any window of size batch_size,
    no two pairs have the same cluster_id. Best-effort greedy round-robin.
    """
    buckets = defaultdict(deque)
    for r in pairs:
        buckets[r["cluster_id"]].append(r)
    keys = list(buckets.keys())
    random.shuffle(keys)

    ordered = []
    while buckets:
        used = set()
        batch = []
        for k in list(keys):
            if k in buckets and k not in used and buckets[k]:
                batch.append((buckets[k].popleft(), k))
                used.add(k)
                if len(batch) == batch_size:
                    break
        ordered.extend(batch)
        # prune empty buckets
        keys = [k for k in keys if k in buckets and len(buckets[k]) > 0]
        if not keys and any(len(v)>0 for v in buckets.values()):
            keys = [k for k,v in buckets.items() if len(v)>0]
            random.shuffle(keys)
        # remove empties
        for k in list(buckets.keys()):
            if not buckets[k]:
                buckets.pop(k, None)
    return ordered

class PreBatchedDataset(Dataset):
    """
    Dataset that returns InputExample in pre-computed order.
    DataLoader will slice contiguous batches of size BATCH_SIZE.
    """
    def __init__(self, ordered_items:List[Tuple[dict,str]], id2text:Dict[str,str], augment_reverse:bool=True):
        self.examples = []
        for r, cid in ordered_items:
            t1 = id2text.get(r["id1"], "")
            t2 = id2text.get(r["id2"], "")
            if not t1 or not t2: 
                continue
            self.examples.append(InputExample(texts=[t1, t2]))
            if augment_reverse:
                self.examples.append(InputExample(texts=[t2, t1]))  # symmetric
    def __len__(self):
        return len(self.examples)
    def __getitem__(self, idx):
        return self.examples[idx]

# =========================
# Training & Eval
# =========================
def train_sft(cfg):
    set_seed(cfg["SEED"])
    Path(cfg["OUT_DIR"]).mkdir(parents=True, exist_ok=True)

    # Load articles and SFT pairs
    id2a = load_articles(cfg["ARTICLES_TRAIN"], cfg)
    sft_pairs = load_sft_pairs(cfg["SFT_PAIRS_TRAIN"])
    # Shuffle then reorder to enforce event-disjoint batches
    random.shuffle(sft_pairs)
    ordered = build_event_disjoint_order(sft_pairs, cfg["BATCH_SIZE"])

    # Map id -> prepared text
    id2text = {aid: a["_text"] for aid, a in id2a.items()}

    # Build dataset & loader
    ds = PreBatchedDataset(ordered, id2text, augment_reverse=True)
    train_loader = DataLoader(ds, batch_size=cfg["BATCH_SIZE"], shuffle=False, drop_last=False)

    # Load model
    device = cfg["DEVICE"] or "cuda"
    model = SentenceTransformer(cfg["MODEL_NAME"], device=device)
    model.max_seq_length = cfg["MAX_SEQ_LEN"]

    # MNRL loss
    loss_fn = losses.MultipleNegativesRankingLoss(model)

    # Warmup = 10% of total steps
    total_steps = math.ceil(len(train_loader) * cfg["EPOCHS"])
    warmup_steps = int(0.1 * total_steps)

    print(f"[SFT] examples={len(ds)}  batches/epoch={len(train_loader)}  epochs={cfg['EPOCHS']}  total_steps≈{total_steps}  warmup={warmup_steps}")
    print(f"[SFT] device={device}  amp={cfg['USE_AMP']}  max_seq_len={cfg['MAX_SEQ_LEN']}  batch_size={cfg['BATCH_SIZE']}")

    # Fit
    model.fit(
        train_objectives=[(train_loader, loss_fn)],
        epochs=cfg["EPOCHS"],
        warmup_steps=warmup_steps,
        use_amp=cfg["USE_AMP"],
        show_progress_bar=True
    )

    # Save model
    out_path = os.path.join(cfg["OUT_DIR"], "encoder-sft-minilm")
    model.save(out_path)
    print("[SFT] saved to:", out_path)
    return model

def l2norm(x:np.ndarray):
    return x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-9)

def encode_texts(model, texts:List[str], batch_size:int=128) -> np.ndarray:
    vecs = model.encode(
        texts, batch_size=batch_size, convert_to_numpy=True,
        normalize_embeddings=True, show_progress_bar=True
    )
    return vecs.astype(np.float32)

def eval_pairs(model, articles_path:str, pairs_path:str, cfg, fixed_tau=None):
    id2a = load_articles(articles_path, cfg)
    id2text = {aid: a["_text"] for aid,a in id2a.items()}

    # Collect unique ids for encoding
    ids = list(id2text.keys())
    texts = [id2text[i] for i in ids]
    embs = encode_texts(model, texts, batch_size=max(32, cfg["BATCH_SIZE"]//2))
    id2emb = {ids[i]: embs[i] for i in range(len(ids))}

    # Compute cosine per pair
    rows = load_eval_pairs(pairs_path)
    y_true, scores = [], []
    miss = 0
    for r in rows:
        a = id2emb.get(r["id1"]); b = id2emb.get(r["id2"])
        if a is None or b is None:
            miss += 1
            continue
        s = float(np.dot(a,b))
        scores.append(s)
        y_true.append(int(r["label"]))
    if miss:
        print(f"[Eval] missing embeddings for {miss} pairs (likely ids not present in articles file)")

    y_true = np.array(y_true, dtype=np.int32)
    scores = np.array(scores, dtype=np.float32)

    # Pick threshold for target precision on this split
    #best = pick_threshold_for_precision(y_true, scores, cfg["TARGET_PRECISION"])
    if fixed_tau is None:
        best = pick_threshold_for_precision(y_true, scores, cfg["TARGET_PRECISION"])
        tau = best["tau"]
    else:
        tau = fixed_tau
        best = {"tau": float(tau)}
    y_pred = (scores >= best["tau"]).astype(int)
    p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    auc = roc_auc_score(y_true, scores)
    return {"tau": best["tau"], "precision": float(p), "recall": float(r), "f1": float(f1), "auc": float(auc)}

def main():
    cfg = CONFIG
    # Train
    model = train_sft(cfg)
    # Eval on val/test
    print("=== Eval: VAL ===")
    val_metrics = eval_pairs(model, cfg["ARTICLES_VAL"], cfg["VAL_PAIRS"], cfg)
    print(val_metrics)
    print("=== Eval: TEST ===")
    test_metrics = eval_pairs(model, cfg["ARTICLES_TEST"], cfg["TEST_PAIRS"], cfg)
    print(test_metrics)
    # Save a small report
    write_json(os.path.join(cfg["OUT_DIR"], "sft_report.json"),
               {"val": val_metrics, "test": test_metrics, "config": cfg})

if __name__ == "__main__":
    main()