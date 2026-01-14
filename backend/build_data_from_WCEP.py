import gzip, json, random, itertools, math
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from collections import defaultdict
from datetime import datetime, timezone

# ========== 可复现随机 ==========
def set_seed(seed: int):
    random.seed(seed)

# ========== 读取 WCEP ==========
def read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)

# ========== 文本与特征 ==========
def tokenize_title(t: str):
    if not t: return []
    t = t.lower()
    out = []
    buf = []
    for ch in t:
        if ch.isalnum() or ch.isspace():
            buf.append(ch)
        else:
            buf.append(" ")
    for tok in "".join(buf).split():
        if len(tok) > 1:
            out.append(tok)
    return out

def jaccard(a_tokens, b_tokens):
    A, B = set(a_tokens), set(b_tokens)
    if not A and not B: return 0.0
    return len(A & B) / max(1, len(A | B))

def hash32(s: str):
    # FNV-1a 32-bit (稳定、可复现)
    h = 2166136261
    for c in s.encode("utf-8", errors="ignore"):
        h ^= c
        h = (h * 16777619) & 0xFFFFFFFF
    return h

def hash64(s: str):
    a = hash32(s)
    b = hash32(s + "#")
    return (a << 32) | b

def simhash64(text: str):
    # 简单 TF 权重 simhash（64 位）
    toks = tokenize_title(text)  # 对正文也可用更完整分词，这里沿用简化版
    if not toks:
        return 0
    weights = defaultdict(int)
    for t in toks:
        weights[t] += 1
    bits = [0]*64
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

def hamming64(a: int, b: int):
    x = a ^ b
    cnt = 0
    while x:
        cnt += x & 1
        x >>= 1
    return cnt

def normalize_url(url: str):
    try:
        u = urlparse(url)
        host = u.hostname or ""
        # 去掉 m. 前缀
        if host.startswith("m."):
            host = host[2:]
        # 去掉常见 tracking 参数
        qs = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
              if not (k.startswith("utm_") or k in {"gclid", "fbclid"})]
        # 去掉末尾斜杠与 AMP 尾缀
        path = (u.path or "").rstrip("/")
        if path.endswith("/amp"):
            path = path[:-4]
        newu = u._replace(netloc=host, query=urlencode(sorted(qs)), path=path)
        return urlunparse(newu)
    except Exception:
        return url

def extract_domain(url: str):
    try:
        return (urlparse(url).hostname or "").lower()
    except:
        return ""

def parse_time_iso(t: str):
    # WCEP 常为 ISO 格式；尽量稳健解析
    if not t:
        return None
    try:
        if t.endswith("Z"):
            return datetime.fromisoformat(t.replace("Z", "+00:00"))
        return datetime.fromisoformat(t)
    except Exception:
        return None

def days_diff(t1, t2):
    if not t1 or not t2: return None
    return abs((t1 - t2).days)

# ========== 采样与生成 ==========
def build_articles(split_path, max_events=None, max_articles_per_event=5):
    """
    返回 articles 列表与 by_cluster 索引
    """
    articles = []
    by_cluster = defaultdict(list)

    for ev in read_jsonl_gz(split_path):
        cid = ev.get("id")
        arts = ev.get("articles", [])
        if not cid or not arts: 
            continue

        # 先按时间排序，保证确定性
        arts_sorted = sorted(
            arts,
            key=lambda a: a.get("time") or ""
        )

        # 截断每个事件的文章数，控制规模
        arts_take = arts_sorted[:max_articles_per_event]

        for a in arts_take:
            aid = a.get("id")
            title = a.get("title") or ""
            url = a.get("url") or ""
            # 文本优先取 content/text（具体字段名以你数据为准）
            text = a.get("content") or a.get("text") or ""
            tiso = parse_time_iso(a.get("time") or "")
            nurl = normalize_url(url)
            dom = extract_domain(nurl)
            # 计算 SimHash（对正文也可以更细致处理；此处简化）
            sh = simhash64(title + " " + text[:2000])  # 截断避免过长

            item = {
                "id": aid,
                "cluster_id": cid,
                "title": title,
                "url": url,
                "canonical_url": nurl,
                "source_domain": dom,
                "time_iso": tiso.isoformat() if tiso else None,
                "text": text,
                "simhash64": sh,
                "title_tokens": tokenize_title(title),
            }
            articles.append(item)
            by_cluster[cid].append(item)

        if max_events is not None and len(by_cluster) >= max_events:
            break

    # 为确定性，整体按 (cluster_id, id) 排序
    articles.sort(key=lambda r: (r["cluster_id"], r["id"] or ""))
    return articles, by_cluster

def sample_positive_pairs(by_cluster, max_pos_pairs_per_cluster=10, seed=42):
    set_seed(seed)
    pairs_pos = []
    for cid, arts in by_cluster.items():
        if len(arts) < 2:
            continue
        # 所有两两组合
        comb = list(itertools.combinations(arts, 2))
        # 打乱后截断
        random.shuffle(comb)
        comb = comb[:max_pos_pairs_per_cluster]
        for a, b in comb:
            pairs_pos.append((a, b, 1))
    return pairs_pos

def sample_negative_pairs(articles, by_cluster, negatives_per_positive=1, seed=42):
    """
    负样本：跨簇采样。尽量做“困难负样本”：同日或同域名优先；
    简化实现：对每个正样本需求量给出预算后，总体随机从跨簇对里抽取，
    并加上一些“同日/同域名”的加权优先（这里用两阶段筛选近似实现）。
    """
    set_seed(seed)
    # 建索引：按日期、按域名聚类
    date_buckets = defaultdict(list)
    domain_buckets = defaultdict(list)

    for a in articles:
        day = (a["time_iso"] or "")[:10]
        if day: date_buckets[day].append(a)
        if a["source_domain"]: domain_buckets[a["source_domain"]].append(a)

    # 全部文章列表
    all_arts = articles

    def pick_hard_negative(a):
        # 优先同日不同簇
        day = (a["time_iso"] or "")[:10]
        cand = [x for x in date_buckets.get(day, []) if x["cluster_id"] != a["cluster_id"]]
        if not cand:
            # 次优先同域名不同簇
            cand = [x for x in domain_buckets.get(a["source_domain"], []) if x["cluster_id"] != a["cluster_id"]]
        if not cand:
            # 退化为任意跨簇
            # 为保证确定性，先过滤再随机
            cand = [x for x in all_arts if x["cluster_id"] != a["cluster_id"]]
        return random.choice(cand) if cand else None

    return pick_hard_negative

def build_pairs(articles, by_cluster, max_pos_pairs_per_cluster=10, negatives_per_positive=1, seed=42):
    # 正样本
    pos = sample_positive_pairs(by_cluster, max_pos_pairs_per_cluster, seed)
    # 负样本“挑选器”
    pick_neg_for = sample_negative_pairs(articles, by_cluster, negatives_per_positive, seed)

    pairs = []
    # 构造正样本对
    for a, b, lab in pos:
        pairs.append((a, b, lab))
        # 为每个正样本配若干负样本
        for _ in range(negatives_per_positive):
            # 对 a 找负样本
            n = pick_neg_for(a)
            if n:
                pairs.append((a, n, 0))

    # 为确定性排序（不改变分布，只改变输出顺序）
    pairs.sort(key=lambda t: (t[0]["cluster_id"], t[0]["id"] or "", t[1]["id"] or "", -t[2]))
    return pairs

def pair_features(a, b):
    # U: 规范 URL 是否相等
    U = 1 if (a["canonical_url"] == b["canonical_url"] and a["canonical_url"]) else 0
    # T: 标题 Jaccard
    T = jaccard(a["title_tokens"], b["title_tokens"])
    # Sh: SimHash 相似度
    dH = hamming64(a["simhash64"], b["simhash64"])
    Sh = 1.0 - (dH / 64.0)
    # 时间差（天）
    t1 = parse_time_iso(a["time_iso"]) if isinstance(a["time_iso"], str) else None
    t2 = parse_time_iso(b["time_iso"]) if isinstance(b["time_iso"], str) else None
    dt = days_diff(t1, t2)
    # 是否同域
    domain_same = 1 if a["source_domain"] == b["source_domain"] and a["source_domain"] else 0
    return U, T, Sh, (dt if dt is not None else -1), domain_same

def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def generate_split(split_name, split_path, out_dir, *,
                   seed=42,
                   max_events=None,
                   max_articles_per_event=5,
                   max_pos_pairs_per_cluster=10,
                   negatives_per_positive=1):
    print(f"[{split_name}] loading...")
    set_seed(seed)
    articles, by_cluster = build_articles(
        split_path,
        max_events=max_events,
        max_articles_per_event=max_articles_per_event
    )
    print(f"[{split_name}] clusters={len(by_cluster)}, articles={len(articles)}")

    # 写出 articles
    art_out = [dict(a, **{"split": split_name}) for a in articles]
    write_jsonl(f"{out_dir}/articles.{split_name}.jsonl", art_out)

    # 构造 pairs
    pairs_raw = build_pairs(
        articles, by_cluster,
        max_pos_pairs_per_cluster=max_pos_pairs_per_cluster,
        negatives_per_positive=negatives_per_positive,
        seed=seed
    )
    pairs_out = []
    for a, b, lab in pairs_raw:
        U, T, Sh, dt, dom_same = pair_features(a, b)
        pairs_out.append({
            "id1": a["id"], "id2": b["id"], "label": lab,
            "cluster_id1": a["cluster_id"], "cluster_id2": b["cluster_id"],
            "U": U, "T": round(T, 4), "Sh": round(Sh, 4),
            "time_diff_days": dt, "domain_same": dom_same,
            "split": split_name
        })
    write_jsonl(f"{out_dir}/pairs.{split_name}.jsonl", pairs_out)
    print(f"[{split_name}] pairs={len(pairs_out)} written.")

# ========== 示例调用 ==========
if __name__ == "__main__":
    # 按需修改路径
    BASE = "WCEP"
    OUT = "out_wcep_posttrain"
    SEED = 2026

    # 控制规模：每个 split 最多取 N 个事件，每事件最多取 K 篇文章，每簇生成 P 个正样本，每个正样本配 R 个负样本
    LIMITS = dict(
        seed=SEED,
        max_events=200,              # 限定事件数量（可调小以快速出结果）
        max_articles_per_event=5,    # 控制每事件采样文章数
        max_pos_pairs_per_cluster=8, # 每簇最多正样本对
        negatives_per_positive=1     # 每个正样本配 1 个负样本
    )

    generate_split("train", f"{BASE}/train.jsonl.gz", OUT, **LIMITS)
    generate_split("val",   f"{BASE}/val.jsonl.gz",   OUT, **LIMITS)
    generate_split("test",  f"{BASE}/test.jsonl.gz",  OUT, **LIMITS)


    