from fastapi import FastAPI, HTTPException
from models import ArticleInput, ArticleResponse, SimilarArticle
from engine import EmbeddingEngine
from storage import save_article, load_all
from extract_content import extract_article_content
from pydantic import BaseModel
import time

# NEW
import os, json
from datetime import datetime, timezone
import math

app = FastAPI(title="SeenIt API")
engine = EmbeddingEngine()

# NEW: URL extraction model
class URLRequest(BaseModel):
    url: str

# =========================
# Load post-train config
# =========================
CONFIG_PATH = os.getenv("SEENIT_CONFIG", "../backend/out_posttrain_minilm/post_train_config.minilm.json")

POST_CFG = None
TAU_EMBED = 0.7
LOGREG = None    # optional

def _sigmoid(x: float) -> float:
    # numerically safe sigmoid
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    else:
        z = math.exp(x)
        return z / (1.0 + z)

def _load_post_cfg():
    global POST_CFG, TAU_EMBED, LOGREG
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            POST_CFG = json.load(f)

        # Embed-only threshold
        TAU_EMBED = float(POST_CFG.get("post_train", {}).get("tau_embed_only", TAU_EMBED))

        # Optional: logistic regression calibration
        post_train = POST_CFG.get("post_train", {})
        feature_cols = post_train.get("feature_cols", [])
        lr = post_train.get("logreg", None)
        if lr and isinstance(feature_cols, list) and len(feature_cols) > 0:
            LOGREG = {
                "feature_cols": feature_cols,
                "weights": lr.get("weights", []),
                "bias": float(lr.get("bias", 0.0)),
                "tau_prob": float(lr.get("tau_prob", 0.5)),
            }

        print(f"[SeenIt] loaded config: {CONFIG_PATH}")
        print(f"[SeenIt] tau_embed_only = {TAU_EMBED}")
        if LOGREG:
            print(f"[SeenIt] logreg enabled with features {LOGREG['feature_cols']} and tau_prob={LOGREG['tau_prob']}")
        else:
            print("[SeenIt] logreg disabled (using embed-only threshold)")

    except Exception as e:
        print(f"[SeenIt] could not load config {CONFIG_PATH}: {e}")
        POST_CFG = None
        LOGREG = None

_load_post_cfg()

def _time_diff_days(ts_iso: str, now_iso: str) -> float:
    # ISO strings -> absolute diff in days
    try:
        t1 = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        return abs((t2 - t1).total_seconds()) / 86400.0
    except Exception:
        return 0.0

def _logreg_accept(E: float, domain_same: float, time_diff_days: float) -> bool:
    """
    Uses post-train logistic regression if available.
    IMPORTANT: We only compute a subset of features at runtime:
      - E (embedding cosine)
      - domain_same
      - time_diff_days
    If the config expects other features (U/T/Sh), we fallback to embed-only.
    """
    if not LOGREG:
        return E >= TAU_EMBED

    cols = LOGREG["feature_cols"]
    w = LOGREG["weights"]
    b = LOGREG["bias"]
    tau_prob = LOGREG["tau_prob"]

    # If config expects features we don't have, fallback
    supported = {"E", "domain_same", "time_diff_days"}
    if any(c not in supported for c in cols):
        return E >= TAU_EMBED

    # Build x in the SAME order as feature_cols
    feat_map = {
        "E": float(E),
        "domain_same": float(domain_same),
        "time_diff_days": float(time_diff_days),
    }
    x = [feat_map[c] for c in cols]

    # linear score -> probability
    s = b + sum(float(wi) * float(xi) for wi, xi in zip(w, x))
    p = _sigmoid(s)
    return p >= tau_prob


@app.post("/article", response_model=ArticleResponse)
async def process_article(article: ArticleInput):
    start = time.time()

    print("===== TEXT TO EMBED =====")
    print(article.title)
    print((article.content or "")[:500])
    print("CONTENT LENGTH:", len(article.content or ""))

    emb = engine.embed(article.title, article.content)

    titles, urls, embs = load_all()
    matches = []

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cur_domain = (article.domain or "")

    max_sim = None

    if embs is not None:
        sims = embs @ emb

        # Track max similarity safely
        try:
            max_sim = float(sims.max())
        except Exception:
            max_sim = None

        for title, url, sim in zip(titles, urls, sims):
            E = float(sim)

            # Compute light runtime features
            # domain_same: 1 if same domain else 0
            # NOTE: storage doesn't currently return domains/timestamps; if you add them later,
            # you can make this more accurate.
            # For now, we only have current domain; for old ones, we can't know -> use 0
            domain_same = 0.0

            # time_diff_days: same issue (we don't have stored timestamps here) -> 0
            time_diff_days = 0.0

            # decision: logreg (if usable) else tau_embed_only
            if _logreg_accept(E, domain_same, time_diff_days):
                matches.append(
                    SimilarArticle(
                        title=title,
                        url=url,
                        similarity=E
                    )
                )

    save_article(article, emb)

    print("MAX SIMILARITY:", max_sim)

    matches.sort(key=lambda x: x.similarity, reverse=True)

    cluster_id = matches[0].url if matches else article.url

    return {
        "similar_found": len(matches) > 0,
        "cluster_id": cluster_id,
        "matches": matches[:5]
    }


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/extract-url", response_model=ArticleResponse)
async def extract_and_process_url(request: URLRequest):
    """
    Extract content from URL and process it for similarity
    This endpoint combines content extraction + similarity detection
    """
    try:
        print(f"===== EXTRACTING URL =====")
        print(f"URL: {request.url}")
        
        # Extract content from URL
        extracted = extract_article_content(request.url)
        
        if not extracted.get('title') or not extracted.get('text'):
            raise HTTPException(
                status_code=400, 
                detail="Could not extract article content from URL"
            )
        
        # Create ArticleInput from extracted content
        article = ArticleInput(
            title=extracted['title'],
            content=extracted['text'],
            url=extracted['url'],
            domain=extracted['domain'],
            timestamp=extracted['timestamp']
        )
        
        print(f"Extracted: {article.title}")
        print(f"Content length: {len(article.content)}")
        
        # Process the article (same logic as /article endpoint)
        emb = engine.embed(article.title, article.content)
        
        titles, urls, embs = load_all()
        matches = []

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cur_domain = (article.domain or "")

        max_sim = None

        if embs is not None:
            sims = embs @ emb

            try:
                max_sim = float(sims.max())
            except Exception:
                max_sim = None

            for title, url, sim in zip(titles, urls, sims):
                E = float(sim)
                domain_same = 0.0
                time_diff_days = 0.0

                if _logreg_accept(E, domain_same, time_diff_days):
                    matches.append(
                        SimilarArticle(
                            title=title,
                            url=url,
                            similarity=E
                        )
                    )

        save_article(article, emb)

        print("MAX SIMILARITY:", max_sim)

        matches.sort(key=lambda x: x.similarity, reverse=True)
        cluster_id = matches[0].url if matches else article.url

        return {
            "similar_found": len(matches) > 0,
            "cluster_id": cluster_id,
            "matches": matches[:5]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error processing URL: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing URL: {str(e)}")


@app.get("/extract-only/{url:path}")  
async def extract_content_only(url: str):
    """
    Just extract content from URL without similarity processing
    Useful for testing content extraction
    """
    try:
        extracted = extract_article_content(url)
        return extracted
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")