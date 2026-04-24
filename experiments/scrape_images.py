import os
import json
import orjson
import hashlib
import requests
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO
import imagehash
from scrape_helper import *

# =========================
# Config
# =========================
ARTICLES_PATH = "out_wcep_dataset_sft/articles.train.jsonl"
OUT_DIR = "images/train"
META_OUT = "images/train_meta.jsonl"
MAX_ITEMS = 10
TIMEOUT = 12
USER_AGENT = "SeenItBot/0.1 (research; contact: zs1025)"

MIN_BYTES = 20000     # reject tiny placeholders
MIN_WIDTH = 400       # reject very small images

# =========================
# Utilities
# =========================
def read_jsonl(path, limit=None):
    count = 0
    with open(path, "rb") as f:
        for line in f:
            if not line.strip():
                continue
            obj = orjson.loads(line)
            yield obj
            count += 1
            if limit and count >= limit:
                break

def resolve(base_url, link):
    try:
        return urljoin(base_url, link) if link else None
    except Exception:
        return None

def best_src_from_srcset(srcset):
    # pick largest width candidate
    candidates = []
    for item in srcset.split(","):
        parts = item.strip().split()
        if not parts:
            continue
        url = parts[0]
        w = 0
        if len(parts) > 1 and parts[1].endswith("w"):
            try:
                w = int(parts[1][:-1])
            except:
                pass
        candidates.append((w, url))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    return None

def parse_jsonld_images(soup):
    imgs = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.text)
            items = data if isinstance(data, list) else [data]
            for it in items:
                if isinstance(it, dict) and it.get("@type") in ("NewsArticle", "Article"):
                    img = it.get("image")
                    if isinstance(img, str):
                        imgs.append(img)
                    elif isinstance(img, dict) and img.get("url"):
                        imgs.append(img["url"])
                    elif isinstance(img, list):
                        for x in img:
                            if isinstance(x, str):
                                imgs.append(x)
                            elif isinstance(x, dict) and x.get("url"):
                                imgs.append(x["url"])
        except Exception:
            continue
    return imgs

def extract_lead_image_url(page_url, html_text=None, session=None, timeout=12, ua="SeenItBot/0.1", domain_blocklist=None):
    import requests
    session = session or requests.Session()
    headers = {"User-Agent": ua}
    if html_text is None:
        r = session.get(page_url, headers=headers, timeout=timeout)
        r.raise_for_status()
        html_text = r.text
    soup = BeautifulSoup(html_text, "html.parser")

    # Collect candidates
    candidates = []
    org_logos = set()

    # OG/Twitter
    for prop in ["og:image","og:image:url","twitter:image"]:
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            u = resolve(page_url, tag["content"])
            if u: candidates.append({"url": u, "source": "meta_og", "alt":"", "classes":[]})

    # JSON-LD
    jsonld_cands, org_logos = parse_jsonld_images(soup, page_url)
    candidates += jsonld_cands

    # Article/main
    candidates += gather_article_scope_images(soup, page_url)

    # Fallback: first <img>
    if not candidates:
        img = soup.find("img")
        if img:
            src = best_src_from_srcset(img.get("srcset","")) or img.get("src")
            u = resolve(page_url, src)
            if u: candidates.append({"url": u, "source": "fallback_img", "alt": img.get("alt") or "", "classes": img.get("class") or []})

    if not candidates:
        return None

    # Domain-level blocklist (paths/patterns or pHashes you accumulated)
    domain = urllib.parse.urlparse(page_url).hostname or ""
    blocked_urls = set()
    if domain_blocklist:
        blocked_urls |= set(domain_blocklist.get(domain, []))

    # Score and pick best
    best_score, best = -1.0, None
    for c in candidates:
        url = c["url"]; alt = c.get("alt",""); classes = c.get("classes",[])
        if url in org_logos:                 # explicitly skip publisher logos
            continue
        if url in blocked_urls:              # known domain-level blocked image
            continue
        # Hard keyword filter
        if is_logo_like(url, alt, classes):
            continue
        # Base score by source
        src = c.get("source","")
        if src == "meta_og":
            score = 0.6   # lower than before; OG can be a default social-card
        elif src == "jsonld_article":
            score = 0.7
        elif src == "jsonld_primary":
            score = 0.5   # often default primary
        elif src == "article_figure":
            score = 0.75  # figure with caption tends to be lead photo
            if c.get("has_caption"): score += 0.1
        elif src == "article_dom":
            score = 0.65 + (0.1 if any(cls in HERO_CLASSES for cls in classes) else 0.0)
        else:
            score = 0.3
        # Size/aspect hints from attributes
        w = c.get("width_attr"); h = c.get("height_attr")
        score += size_hint_score(w, h)
        score += aspect_ratio_score(w, h)

        # Penalize suspicious square OG (1:1) explicitly
        if src in ("meta_og","jsonld_primary") and (w and h and abs(w - h) < 10):
            score -= 0.3

        if score > best_score:
            best_score, best = score, c

    return best["url"] if best else None

def fetch_and_validate_image(img_url):
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(img_url, headers=headers, timeout=TIMEOUT, stream=True)
    r.raise_for_status()
    ctype = r.headers.get("Content-Type", "")
    if "image" not in ctype.lower():
        return None, "not_image_content_type"
    data = r.content
    if len(data) < MIN_BYTES:
        return None, "too_small_bytes"
    try:
        im = Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        return None, "decode_error"
    if im.width < MIN_WIDTH:
        return None, "too_small_width"
    return (data, im), "ok"

def sha256_bytes(b):
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)

def ext_from_content_type(ctype):
    ctype = ctype.lower()
    if "jpeg" in ctype or "jpg" in ctype:
        return ".jpg"
    if "png" in ctype:
        return ".png"
    if "webp" in ctype:
        return ".webp"
    if "gif" in ctype:
        return ".gif"
    return ".jpg"  # default

# =========================
# Main
# =========================
def main():
    ensure_dir(OUT_DIR)
    meta_out_f = open(META_OUT, "ab")  # append-safe

    processed = 0
    for article in read_jsonl(ARTICLES_PATH):
        if processed >= MAX_ITEMS:
            break
        aid = article.get("id")
        page_url = article.get("canonical_url") or article.get("url")
        if not page_url or not aid:
            continue

        record = {
            "article_id": aid,
            "cluster_id": article.get("cluster_id"),
            "page_url": page_url,
            "image_url": None,
            "saved_path": None,
            "status": "init",
            "sha256": None,
            "pHash": None,
            "width": None,
            "height": None,
            "bytes": None,
            "content_type": None,
        }

        try:
            img_url = extract_lead_image_url(page_url)
            record["image_url"] = img_url
            if not img_url:
                record["status"] = "no_image_found"
                meta_out_f.write(orjson.dumps(record) + b"\n")
                processed += 1
                continue

            headers = {"User-Agent": USER_AGENT}
            r = requests.get(img_url, headers=headers, timeout=TIMEOUT, stream=True)
            r.raise_for_status()
            ctype = r.headers.get("Content-Type", "")
            (data, im), status = fetch_and_validate_image(img_url)
            if status != "ok":
                record["status"] = status
                meta_out_f.write(orjson.dumps(record) + b"\n")
                processed += 1
                continue

            h = sha256_bytes(data)
            record["sha256"] = h
            record["pHash"] = str(imagehash.phash(im))
            record["width"] = im.width
            record["height"] = im.height
            record["bytes"] = len(data)
            record["content_type"] = ctype

            # Use sha256 as filename to deduplicate identical images
            ext = ext_from_content_type(ctype)
            fname = f"{h}{ext}"
            fpath = os.path.join(OUT_DIR, fname)
            if not os.path.exists(fpath):
                with open(fpath, "wb") as f:
                    f.write(data)
            record["saved_path"] = fpath
            record["status"] = "ok"

        except requests.RequestException as e:
            record["status"] = f"http_error:{type(e).__name__}"
        except Exception as e:
            record["status"] = f"error:{type(e).__name__}"

        meta_out_f.write(orjson.dumps(record) + b"\n")
        processed += 1

    meta_out_f.close()
    print(f"Done. Wrote metadata to {META_OUT}, saved images under {OUT_DIR}, processed={processed}")

if __name__ == "__main__":
    main()