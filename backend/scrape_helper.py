import re, json, urllib.parse
from bs4 import BeautifulSoup

LOGO_WORDS = {"logo","brand","branding","favicon","sprite","icon","badge","header","footer","social","avatar","default","dft","placeholder"}
HERO_CLASSES = {"hero","lead","featured","article-image","post-image","story-image","wp-post-image","entry-image","image-hero","media__image","post-thumbnail"}
ARTICLE_SELECTORS = ["article","[role=main]","main",".article",".post",".story",".content__article-body",".entry-content",".post-content"]

def resolve(base, link):
    try:
        return urllib.parse.urljoin(base, link) if link else None
    except Exception:
        return None

def best_src_from_srcset(srcset):
    candidates = []
    for item in srcset.split(","):
        parts = item.strip().split()
        if not parts: continue
        url = parts[0]; w = 0
        if len(parts) > 1 and parts[1].endswith("w"):
            try: w = int(parts[1][:-1])
            except: pass
        candidates.append((w, url))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    return None

def parse_jsonld_images(soup, page_url):
    imgs = []
    org_logos = set()
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.text)
            items = data if isinstance(data, list) else [data]
            for it in items:
                if not isinstance(it, dict): continue
                typ = it.get("@type","")
                # Collect Organization.logo to block later
                if typ == "Organization" and isinstance(it.get("logo"), dict):
                    u = it["logo"].get("url") or it["logo"].get("contentUrl")
                    if u: org_logos.add(resolve(page_url, u))
                # NewsArticle/Article.image candidates
                if typ in ("NewsArticle","Article"):
                    img = it.get("image"); cand = []
                    if isinstance(img, str): cand = [img]
                    elif isinstance(img, dict) and img.get("url"): cand = [img["url"]]
                    elif isinstance(img, list):
                        for x in img:
                            if isinstance(x, str): cand.append(x)
                            elif isinstance(x, dict) and x.get("url"): cand.append(x["url"])
                    for u in cand:
                        uu = resolve(page_url, u)
                        if uu: imgs.append({"url": uu, "source": "jsonld_article"})
                    # primaryImageOfPage sometimes points to a default site image; treat as candidate but low priority
                    pimg = it.get("primaryImageOfPage")
                    if isinstance(pimg, dict) and pimg.get("@id"):
                        uu = resolve(page_url, pimg["@id"])
                        if uu: imgs.append({"url": uu, "source": "jsonld_primary"})
        except Exception:
            continue
    return imgs, org_logos

def is_logo_like(url, alt, classes):
    url_l = (url or "").lower(); alt_l = (alt or "").lower(); cls_l = " ".join(classes or []).lower()
    blob = " ".join([url_l, alt_l, cls_l])
    if any(w in blob for w in LOGO_WORDS): return True
    if re.search(r"/(logo|favicon|sprite|icons?)/", url_l): return True
    if url_l.startswith("data:image"): return True
    return False

def aspect_ratio_score(w, h):
    if not w or not h: return 0.0
    r = w / max(1, h)
    if 1.2 <= r <= 2.2: return 0.25   # prefer wide hero-ish
    if 0.8 <= r <= 1.2: return 0.05   # square-ish (logos/avatars common)
    return 0.0

def size_hint_score(w, h):
    if (w and w >= 800) or (h and h >= 450): return 0.25
    if (w and w >= 500) or (h and h >= 300): return 0.15
    return 0.0

def gather_article_scope_images(soup, page_url):
    containers = []
    for sel in ARTICLE_SELECTORS:
        containers += soup.select(sel)
    if not containers: containers = [soup]
    candidates, seen = [], set()
    for root in containers:
        # consider figures with figcaption first
        for fig in root.find_all("figure"):
            img = fig.find("img")
            if not img: continue
            url = best_src_from_srcset(img.get("srcset","")) or img.get("src")
            uu = resolve(page_url, url)
            if not uu or uu in seen: continue
            seen.add(uu)
            alt = img.get("alt") or ""; classes = img.get("class") or []
            w = None; h = None
            try:
                w = int(img.get("width")) if img.get("width") else None
                h = int(img.get("height")) if img.get("height") else None
            except: pass
            has_caption = bool(fig.find("figcaption"))
            candidates.append({
                "url": uu, "source": "article_figure",
                "alt": alt, "classes": classes,
                "width_attr": w, "height_attr": h,
                "has_caption": has_caption
            })
        # fallback: all <img> in article/main
        for img in root.find_all("img"):
            url = best_src_from_srcset(img.get("srcset","")) or img.get("src")
            uu = resolve(page_url, url)
            if not uu or uu in seen: continue
            seen.add(uu)
            alt = img.get("alt") or ""; classes = img.get("class") or []
            w = None; h = None
            try:
                w = int(img.get("width")) if img.get("width") else None
                h = int(img.get("height")) if img.get("height") else None
            except: pass
            candidates.append({
                "url": uu, "source": "article_dom",
                "alt": alt, "classes": classes,
                "width_attr": w, "height_attr": h,
                "has_caption": False
            })
    return candidates

