import gzip, json, random, collections
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from datetime import datetime
from utils import *


# =============================
# CONFIG (edit here)
# =============================
CONFIG = {
    "BASE": "WCEP",                         # path to original WCEP {train|val|test}.jsonl.gz
    "OUT": "out_wcep_dataset",              # output directory
    "SEED": 2026,

    # Post-train (val/test) limits: keep moderate size for calibration & eval
    "LIMITS_PT": {
        "max_events": 200,                  # at most N events
        "max_articles_per_event": 5,        # K
        "max_pos_pairs_per_cluster": 8,     # P
        "negatives_per_positive": 1         # R
    },

    # SFT (train) limits: you can scale up independently of PT
    "LIMITS_SFT": {
        "max_events": 2000,                 # increase for more SFT pairs
        "max_articles_per_event": 6,        # K_train (e.g., 6→ C(6,2)=15 positives per cluster)
        "max_pos_pairs_per_cluster": None,  # None = no cap, else integer cap
        "hard_neg_for_triplet": True,       # if generating triplets, mine one hard negative per anchor
        "generate_triplets": False          # set True if you want triplets for TripletLoss
    },

    # Text building for embeddings/SimHash features
    "TEXT_STRATEGY": "title+lede",          # "title" | "title+lede" | "title+text_clip"
    "TEXT_CLIP_LEN": 2000                   # chars when using title+text_clip
}

# =============================
# Build articles (per split)
# =============================
def article_text(a, text_strategy, clip_len):
    title = a.get("title") or ""
    body  = a.get("content") or a.get("text") or ""
    if text_strategy == "title":
        return title
    if text_strategy == "title+lede":
        # crude lede: first ~512 chars (adjust as needed)
        lede = body[:512]
        return f"{title}\n\n{lede}"
    # title+text_clip
    return f"{title}\n\n{body[:clip_len]}"

def build_articles_for_split(split_path, limits, text_strategy, clip_len):
    max_events = limits["max_events"]
    K = limits["max_articles_per_event"]

    articles = []
    by_cluster = collections.defaultdict(list)

    for ev in read_jsonl_gz(split_path):
        cid = ev.get("id")
        arts = ev.get("articles", [])
        if not cid or not arts:
            continue

        # time sort for deterministic order
        arts_sorted = sorted(arts, key=lambda a: a.get("time") or "")

        # cap articles per event
        take = arts_sorted[:K]

        # deduplicate by normalized URL within cluster (optional but recommended)
        seen_urls = set()
        tmp = []
        for a in take:
            nurl = normalize_url(a.get("url") or "")
            if nurl in seen_urls:
                continue
            seen_urls.add(nurl)
            tmp.append(a)
        take = tmp

        for a in take:
            aid = a.get("id")
            if not aid:
                continue
            nurl = normalize_url(a.get("url") or "")
            dom  = extract_domain(nurl)
            tiso = parse_time_iso(a.get("time") or "")
            text_for_sh = article_text(a, text_strategy, clip_len)
            sh = simhash64_from_text(text_for_sh)

            row = {
                "id": aid,
                "cluster_id": cid,
                "title": a.get("title") or "",
                "url": a.get("url") or "",
                "canonical_url": nurl,             # deterministic normalized URL
                "source_domain": dom,
                "time_iso": tiso.isoformat() if tiso else None,
                "text": (a.get("content") or a.get("text") or ""),
                "title_tokens": tokenize_title(a.get("title") or ""),
                "simhash64": sh
            }
            articles.append(row)
            by_cluster[cid].append(row)

        if max_events is not None and len(by_cluster) >= max_events:
            break

    articles.sort(key=lambda r: (r["cluster_id"], r["id"] or ""))
    return articles, by_cluster

# =============================
# Post-train pairs (val/test)
# =============================
def comb2(n): return n*(n-1)//2 if n >= 2 else 0

def sample_positive_pairs(by_cluster, max_pos_pairs_per_cluster, seed):
    set_seed(seed)
    pos = []
    for cid, arts in by_cluster.items():
        if len(arts) < 2:
            continue
        combs = []
        for i in range(len(arts)):
            for j in range(i+1, len(arts)):
                combs.append((arts[i], arts[j]))
        random.shuffle(combs)
        if max_pos_pairs_per_cluster is not None:
            combs = combs[:max_pos_pairs_per_cluster]
        for a,b in combs:
            pos.append((a,b,1))
    return pos

def build_hard_negative_picker(articles):
    date_buckets = collections.defaultdict(list)
    domain_buckets = collections.defaultdict(list)
    for a in articles:
        day = (a["time_iso"] or "")[:10]
        if day: date_buckets[day].append(a)
        if a["source_domain"]:
            domain_buckets[a["source_domain"]].append(a)

    def pick_neg_for(a):
        day = (a["time_iso"] or "")[:10]
        # same day, different cluster
        cand = [x for x in date_buckets.get(day, []) if x["cluster_id"] != a["cluster_id"]]
        if not cand:
            # same domain, different cluster
            cand = [x for x in domain_buckets.get(a["source_domain"], []) if x["cluster_id"] != a["cluster_id"]]
        return random.choice(cand) if cand else None
    return pick_neg_for

def pair_features(a, b):
    U  = 1 if (a["canonical_url"] and a["canonical_url"] == b["canonical_url"]) else 0
    T  = jaccard(a["title_tokens"], b["title_tokens"])
    dH = hamming64(a["simhash64"], b["simhash64"])
    Sh = 1.0 - (dH / 64.0)
    # day diff and domain-same
    def parse(ts):
        if ts is None: return None
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return None
    t1 = parse(a["time_iso"]); t2 = parse(b["time_iso"])
    dt = (abs((t1 - t2).days) if (t1 and t2) else -1)
    dom_same = 1 if (a["source_domain"] and a["source_domain"] == b["source_domain"]) else 0
    return U, round(T,4), round(Sh,4), dt, dom_same

def build_post_train_pairs(articles, by_cluster, limits, seed):
    P = limits["max_pos_pairs_per_cluster"]
    R = limits["negatives_per_positive"]
    # positives
    pos = sample_positive_pairs(by_cluster, P, seed)
    # negatives
    set_seed(seed)
    pick_neg = build_hard_negative_picker(articles)
    pairs = []
    for a,b,_ in pos:
        pairs.append((a,b,1))
        for _ in range(R):
            n = pick_neg(a)
            if n:
                pairs.append((a,n,0))
    # sort for deterministic output
    pairs.sort(key=lambda t: (t[0]["cluster_id"], t[0]["id"] or "", t[1]["id"] or "", -t[2]))
    # featurize
    out = []
    for a,b,lab in pairs:
        U,T,Sh,dt,dom_same = pair_features(a,b)
        out.append({
            "id1": a["id"], "id2": b["id"], "label": lab,
            "cluster_id1": a["cluster_id"], "cluster_id2": b["cluster_id"],
            "U": U, "T": T, "Sh": Sh,
            "time_diff_days": dt, "domain_same": dom_same
        })
    return out

# =============================
# SFT pairs (train)
# =============================
def build_sft_pairs(by_cluster, limits, seed):
    """
    For MNRL: positives only (same-event). Optionally cap per cluster.
    """
    set_seed(seed)
    Pcap = limits.get("max_pos_pairs_per_cluster", None)
    pairs = []
    for cid, arts in by_cluster.items():
        if len(arts) < 2: continue
        combs = []
        for i in range(len(arts)):
            for j in range(i+1, len(arts)):
                combs.append((arts[i], arts[j]))
        random.shuffle(combs)
        if Pcap is not None:
            combs = combs[:Pcap]
        for a,b in combs:
            pairs.append({"id1": a["id"], "id2": b["id"], "label": 1,
                          "cluster_id": cid})
    # deterministic order
    pairs.sort(key=lambda r: (r["cluster_id"], r["id1"], r["id2"]))
    return pairs

def build_sft_triplets(by_cluster, articles, limits, seed):
    """
    Optional: Triplets (anchor, positive, hard negative).
    """
    if not limits.get("generate_triplets", False):
        return []
    set_seed(seed)
    pick_neg = build_hard_negative_picker(articles)
    triplets = []
    for cid, arts in by_cluster.items():
        if len(arts) < 2: continue
        for i in range(len(arts)-1):
            a = arts[i]; p = arts[i+1]     # simple adjacent positive
            n = pick_neg(a)
            if n:
                triplets.append({"anchor": a["id"], "positive": p["id"], "negative": n["id"],
                                 "cluster_id": cid})
    triplets.sort(key=lambda r: (r["cluster_id"], r["anchor"], r["positive"]))
    return triplets

# =============================
# Driver
# =============================
def main():
    C = CONFIG
    set_seed(C["SEED"])
    BASE = C["BASE"]; OUT = C["OUT"]

    # 1) SFT from original train split
    print("=== SFT (train split) ===")
    sft_limits = C["LIMITS_SFT"]
    arts_tr, byc_tr = build_articles_for_split(
        f"{BASE}/train.jsonl.gz", sft_limits, C["TEXT_STRATEGY"], C["TEXT_CLIP_LEN"]
    )
    print(f"train events (kept): {len(byc_tr)}, articles (kept): {len(arts_tr)}")

    write_jsonl(f"{OUT}/articles.train.jsonl", [dict(a, **{"split":"train"}) for a in arts_tr])

    sft_pairs = build_sft_pairs(byc_tr, sft_limits, C["SEED"])
    write_jsonl(f"{OUT}/sft_pairs.train.jsonl", sft_pairs)
    print(f"SFT positives (pairs): {len(sft_pairs)}")

    sft_triplets = build_sft_triplets(byc_tr, arts_tr, sft_limits, C["SEED"])
    if sft_triplets:
        #write_jsonl(f"{OUT}/sft_triplets.train.jsonl", sft_triplets)
        print(f"SFT triplets: {len(sft_triplets)}")

    # 2) Post-train for val & test
    for split in ["val", "test"]:
        print(f"=== Post-train ({split}) ===")
        pt_limits = C["LIMITS_PT"]
        arts, byc = build_articles_for_split(
            f"{BASE}/{split}.jsonl.gz", pt_limits, C["TEXT_STRATEGY"], C["TEXT_CLIP_LEN"]
        )
        print(f"{split} events (kept): {len(byc)}, articles (kept): {len(arts)}")
        write_jsonl(f"{OUT}/articles.{split}.jsonl", [dict(a, **{"split": split}) for a in arts])

        pairs = build_post_train_pairs(arts, byc, pt_limits, C["SEED"])
        write_jsonl(f"{OUT}/pairs.{split}.jsonl", pairs)
        pos = sum(1 for r in pairs if r["label"] == 1)
        print(f"{split} pairs: {len(pairs)} (pos={pos}, neg={len(pairs)-pos})")

if __name__ == "__main__":
    main()