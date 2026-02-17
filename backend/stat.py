import gzip, json, orjson, collections, math
from statistics import mean, median
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

# -----------------------
# Config: update paths
# -----------------------
BASE = "WCEP"  # directory holding the original split files
DERIVED = "out_wcep_posttrain"  # your derived articles/pairs directory
LIMITS = dict(
    max_events=200,
    max_articles_per_event=5,    # K
    max_pos_pairs_per_cluster=8, # P
    negatives_per_positive=1     # R
)
SPLITS = ["train", "val", "test"]

# -----------------------
# Utilities
# -----------------------
def read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)

def read_jsonl(path):
    with open(path, "rb") as f:
        for line in f:
            if line.strip():
                yield orjson.loads(line)

def comb2(n):
    return n*(n-1)//2 if n >= 2 else 0

def parse_iso(ts):
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts.replace("Z","+00:00")
        return datetime.fromisoformat(ts)
    except Exception:
        return None

# -----------------------
# Original WCEP stats
# -----------------------
def stats_original_split(split):
    path = f"{BASE}/{split}.jsonl.gz"
    events = list(read_jsonl_gz(path))
    num_events = len(events)

    # article counts per event
    ac = []
    all_domains = collections.Counter()
    min_time, max_time = None, None

    for ev in events:
        arts = ev.get("articles", [])
        ac.append(len(arts))
        for a in arts:
            url = a.get("url","")
            host = (urlparse(url).hostname or "").lower()
            if host:
                all_domains[host] += 1
            t = parse_iso(a.get("time"))
            if t:
                min_time = t if (min_time is None or t < min_time) else min_time
                max_time = t if (max_time is None or t > max_time) else max_time

    total_articles = sum(ac)
    ac_sorted = sorted(ac)
    bins = collections.Counter()
    for n in ac:
        k = n if n <= 10 else ">10"
        bins[k] += 1

    # With LIMITS, estimate kept articles and capped positives
    K = LIMITS["max_articles_per_event"]
    P = LIMITS["max_pos_pairs_per_cluster"]
    R = LIMITS["negatives_per_positive"]

    kept_per_event = [min(n, K) for n in ac]
    kept_articles = sum(kept_per_event)
    pos_per_event = [min(comb2(k), P) for k in kept_per_event]
    est_pos = sum(pos_per_event)
    est_total_pairs = est_pos * (1 + R)

    print(f"\n=== Original WCEP :: {split} ===")
    print(f"Events: {num_events}")
    print(f"Articles (total): {total_articles}")
    print(f"Articles per event: min={min(ac) if ac else 0}  median={median(ac) if ac else 0}  mean={round(mean(ac),2) if ac else 0}  max={max(ac) if ac else 0}")
    print("Articles per event bins (1..10, >10):", dict(bins))
    if min_time and max_time:
        print(f"Time span: {min_time.date()} → {max_time.date()}")
    print(f"Kept articles with K={K}: {kept_articles}")
    print(f"Est. positives with cap P={P}: {est_pos}")
    print(f"Est. total pairs with R={R}: {est_total_pairs}")
    print("Top domains:", all_domains.most_common(10))

# -----------------------
# Derived (articles/pairs) stats
# -----------------------
def stats_derived_split(split):
    a_path = f"{DERIVED}/articles.{split}.jsonl"
    p_path = f"{DERIVED}/pairs.{split}.jsonl"

    if not Path(a_path).exists() or not Path(p_path).exists():
        print(f"\n=== Derived :: {split} ===")
        print("Missing derived files:", a_path, p_path)
        return

    arts = list(read_jsonl(a_path))
    pairs = list(read_jsonl(p_path))

    # Articles
    clusters = collections.Counter([a.get("cluster_id") for a in arts])
    by_cluster = collections.defaultdict(list)
    domains = collections.Counter()
    for a in arts:
        by_cluster[a["cluster_id"]].append(a["id"])
        dom = a.get("source_domain")
        if dom: domains[dom] += 1

    # Pairs
    pos = sum(1 for r in pairs if int(r.get("label",0)) == 1)
    neg = len(pairs) - pos

    # Check caps
    Pcap = LIMITS["max_pos_pairs_per_cluster"]
    per_cluster_pos_capped = 0
    per_cluster_actual_pos = collections.Counter()
    for r in pairs:
        if int(r.get("label",0)) == 1:
            per_cluster_actual_pos[r["cluster_id1"]] += 1
    for cid, count in per_cluster_actual_pos.items():
        if count > Pcap:
            per_cluster_pos_capped += 1

    print(f"\n=== Derived :: {split} ===")
    print(f"Articles: {len(arts)}  Unique clusters: {len(clusters)}")
    print(f"Pairs: {len(pairs)}  Positives: {pos}  Negatives: {neg}")
    print("Articles per cluster (kept): min={} median={} mean={:.2f} max={}".format(
        min(len(v) for v in by_cluster.values()) if by_cluster else 0,
        median([len(v) for v in by_cluster.values()]) if by_cluster else 0,
        mean([len(v) for v in by_cluster.values()]) if by_cluster else 0,
        max(len(v) for v in by_cluster.values()) if by_cluster else 0,
    ))
    print("Top domains:", domains.most_common(10))
    print(f"Clusters exceeding positive cap P={Pcap}: {per_cluster_pos_capped} (0 is expected)")

if __name__ == "__main__":
    for sp in SPLITS:
        stats_original_split(sp)
    for sp in SPLITS:
        stats_derived_split(sp)