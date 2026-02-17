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

def extract_lead_image_url(page_url):
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(page_url, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # og:image / twitter:image
    for prop in ["og:image", "twitter:image"]:
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            u = resolve(page_url, tag["content"])
            if u:
                return u

    # JSON-LD NewsArticle.image
    jsonld_imgs = parse_jsonld_images(soup)
    for u in jsonld_imgs:
        uu = resolve(page_url, u)
        if uu:
            return uu

    # <article> img
    art = soup.find("article")
    if art:
        img = art.find("img")
        if img:
            if img.get("srcset"):
                src = best_src_from_srcset(img["srcset"]) or img.get("src")
            else:
                src = img.get("src")
            uu = resolve(page_url, src)
            if uu:
                return uu

    # Fallback: first <img>
    img = soup.find("img")
    if img:
        if img.get("srcset"):
            src = best_src_from_srcset(img["srcset"]) or img.get("src")
        else:
            src = img.get("src")
        uu = resolve(page_url, src)
        if uu:
            return uu

    return None

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