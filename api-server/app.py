from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware  
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from models import ArticleInput, ArticleResponse, SimilarArticle
from engine import EmbeddingEngine
from contextlib import asynccontextmanager
from storage import save_article, load_all, get_article_by_url, normalize_url, get_embeddings_by_urls, get_content_by_urls
from whats_new import compute_whats_new
from llm_summarizer import summarize_whats_new
from extract_content import extract_article_content
from pydantic import BaseModel
import time
import asyncio
import os, json
from typing import Optional
from datetime import datetime, timezone
import math
from dotenv import load_dotenv
from fastapi_users.exceptions import UserAlreadyExists

load_dotenv() # load .env variables

# Clustering
from cluster_utils import compute_centroid, compute_novelty_score
from storage import get_embeddings_by_urls

# Import auth
from auth import (
    User,
    UserCreate,
    UserRead,
    auth_backend,
    create_db_and_tables,
    current_active_user,
    fastapi_users,
)
from datetime import timedelta


# ==================== STARTUP ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    yield

app = FastAPI(title="SeenIt API", lifespan=lifespan)

# Allow all origins in development — lock this down to your extension ID in production
app.add_middleware(          # CORS Middleware
    CORSMiddleware,
    allow_origins=["*"],     # all origins allowed for now | REPLACE WITH ACTUAL ID ONCE READY TO DEPLOY
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = EmbeddingEngine()

# ==================== ERROR HANDLERS ====================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Custom handler for Pydantic validation errors.
    Converts technical validation errors to user-friendly messages.
    """
    errors = exc.errors()
    
    # Extract user-friendly error messages
    error_messages = []
    for error in errors:
        if error['type'] == 'value_error':
            # Custom validator errors (like password validation)
            msg = error.get('msg', '').replace('Value error, ', '')
            error_messages.append(msg)
        elif error['type'] == 'string_too_short':
            field = error['loc'][-1] if error['loc'] else 'field'
            error_messages.append(f"{field.capitalize()} is too short")
        elif error['type'] == 'missing':
            field = error['loc'][-1] if error['loc'] else 'field'
            error_messages.append(f"{field.capitalize()} is required")
        else:
            # Default message
            msg = error.get('msg', 'Validation error')
            error_messages.append(msg)
    
    return JSONResponse(
        status_code=400,
        content={
            "detail": ". ".join(error_messages) if error_messages else "Validation error"
        }
    )

# ==================== AUTH ENDPOINTS ====================

# ── Auth routes ───────────────────────────────────────────────────────────────
# POST /api/auth/login        → { access_token, token_type }
# POST /api/register          → create account
# GET  /api/users/me          → current user info
# PATCH /api/users/me         → update email / change password

app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/api/auth",
    tags=["auth"],
)

# Custom register endpoint with better error messages
@app.post("/api/register", response_model=UserRead, tags=["auth"])
async def register(
    user_create: UserCreate,
    request: Request,
    user_manager = Depends(fastapi_users.get_user_manager)
):
    """
    Register a new user with custom error handling.
    """
    try:
        user = await user_manager.create(user_create, request=request)
        return user
    except UserAlreadyExists:
        raise HTTPException(
            status_code=400,
            detail="A user with this email already exists"
        )
    except Exception as e:
        # Log the error for debugging
        print(f"Registration error: {e}")
        raise HTTPException(
            status_code=400,
            detail="Registration failed. Please try again."
        )
    
app.include_router(
    fastapi_users.get_users_router(UserRead, UserCreate),
    prefix="/api/users",
    tags=["users"],
)
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

# TEMPORARY: Disable post-train tau override.
# The trained tau_embed_only (~0.395) is too permissive for real-world news similarity
# in the browser setting and causes excessive false positives.
# We keep the hardcoded default (0.7) until calibration is re-validated.
# _load_post_cfg()

def _time_diff_days(ts_iso: str, now_iso: str) -> float:
    # ISO strings -> absolute diff in days
    try:
        t1 = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        return abs((t2 - t1).total_seconds()) / 86400.0
    except Exception:
        return 0.0


def _compute_novelty_details(
    current_title: str, current_content: str, reference_urls: list, novelty_score: Optional[float]
) -> Optional[dict]:
    """
    Compute what's new (entities, numbers) when we have similar articles.
    Especially useful when novelty is low (mostly repeated content).
    """
    if not reference_urls or novelty_score is None:
        return None
    try:
        ref_contents = get_content_by_urls(reference_urls)
        if not ref_contents:
            return None
        result = compute_whats_new(current_title, current_content, ref_contents)

        # Optionally refine the summary with FLAN-T5 using the most informative sentences
        sentences = result.get("sentences") or []

        # Option B: if no new-entity sentences found, fall back to first sentences
        # of the current article so the LLM always has something to summarize
        if not sentences and current_content:
            from whats_new import _split_sentences
            sentences = _split_sentences(current_content)[:5]
            print("[SeenIt] no new-entity sentences found, falling back to article lede for LLM")

        if sentences:
            try:
                print(f"[SeenIt] calling summarize_whats_new with {len(sentences)} sentences")
                llm_summary = summarize_whats_new(sentences)
                if llm_summary:
                    result["summary"] = llm_summary
                    print(f"[SeenIt] LLM summary: {llm_summary[:100]}")
            except Exception as e:
                print(f"[SeenIt] LLM summary error: {e}")

        # Do not expose raw sentence list in the API response
        result.pop("sentences", None)

        if result["new_entities"] or result["new_numbers"] or result.get("summary"):
            return result
    except Exception as e:
        print(f"[SeenIt] whats_new error: {e}")
    return None


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
async def process_article(article: ArticleInput, user: User = Depends(current_active_user)):
    start = time.time()
    user_id = str(user.id)  # ← NEW: Get the authenticated user's ID

    # Check if this URL already exists
    article.url = normalize_url(article.url)
    existing = await asyncio.to_thread(get_article_by_url, article.url, user_id)
    if existing:
        print(f"===== URL ALREADY EXISTS FOR USER {user_id}: {article.url} =====")
        # Use existing embedding
        emb = existing['embedding']
        
        # Find matches (excluding self)
        titles, urls, domains, timestamps, embs = await asyncio.to_thread(load_all, user_id) # Added user_id
        matches = []

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cur_domain = existing.get("domain", "")
        
        if embs is not None:
            sims = embs @ emb
            
            for title, url, od, ots, sim in zip(titles, urls, domains, timestamps, sims):
                E = float(sim)
                
                if url == article.url:
                    continue
                
                domain_same = 1.0 if (cur_domain and od and cur_domain == od) else 0.0
                time_diff_days = _time_diff_days(ots, now_iso) if ots else 0.0
                
                if _logreg_accept(E, domain_same, time_diff_days):
                    matches.append(
                        SimilarArticle(
                            title=title,
                            url=url,
                            similarity=E
                        )
                    )
        
        matches.sort(key=lambda x: x.similarity, reverse=True)
        candidate_urls = [article.url] + [m.url for m in matches[:5]]
        cluster_id = min(candidate_urls) if candidate_urls else article.url

        # -----------------------------
        # CLUSTER CENTROID NOVELTY
        # -----------------------------
        
        TOP_K = 5
        top_matches = matches[:TOP_K]
        reference_urls = [m.url for m in top_matches]
        print(f"[SeenIt] reference_urls: {reference_urls}")
        reference_embeddings = await asyncio.to_thread(get_embeddings_by_urls, reference_urls)
        print(f"[SeenIt] reference_embeddings count: {len(reference_embeddings)}")

        novelty = None
        novelty_details = None

        if reference_embeddings:
            centroid = compute_centroid(reference_embeddings)
            novelty_score = compute_novelty_score(emb, centroid)
            print(f"[SeenIt] novelty_score: {novelty_score}")
            novelty = {
                "novelty_score": round(novelty_score, 3),
                "interpretation": (
                    "very new" if novelty_score > 0.6
                    else "somewhat new" if novelty_score > 0.3
                    else "mostly repeated"
                )
            }
            novelty_details = _compute_novelty_details(
            article.title, article.content, reference_urls, novelty_score
            )  # use existing.title/content for the already-exists branch
            print(f"[SeenIt] novelty_details: {novelty_details}")
        else:
            print("[SeenIt] no reference_embeddings — novelty skipped")

        
        return {
            "similar_found": len(matches) > 0,
            "cluster_id": cluster_id,
            "matches": matches[:5],
            "novelty": novelty,
            "novelty_details": novelty_details
        }

    print("===== TEXT TO EMBED =====")
    print(article.title)
    print((article.content or "")[:500])
    print("CONTENT LENGTH:", len(article.content or ""))

    emb = engine.embed(article.title, article.content)

    titles, urls, domains, timestamps, embs = await asyncio.to_thread(load_all, user_id)
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

        for title, url, od, ots, sim in zip(titles, urls, domains, timestamps, sims):
            E = float(sim)
            
            if url == article.url:
                continue 

            # Compute light runtime features
            domain_same = 1.0 if (cur_domain and od and cur_domain == od) else 0.0
            time_diff_days = _time_diff_days(ots, now_iso) if ots else 0.0

            # decision: logreg (if usable) else tau_embed_only
            if _logreg_accept(E, domain_same, time_diff_days):
                matches.append(
                    SimilarArticle(
                        title=title,
                        url=url,
                        similarity=E
                    )
                )

    print("MAX SIMILARITY:", max_sim)

    matches.sort(key=lambda x: x.similarity, reverse=True)
    candidate_urls = [article.url] + [m.url for m in matches[:5]]
    cluster_id = min(candidate_urls) if candidate_urls else article.url


    top_similarity = matches[0].similarity if matches else None
    await asyncio.to_thread(save_article, article, emb, user_id, cluster_id=cluster_id, similarity=top_similarity)
    # -----------------------------
    # CLUSTER CENTROID NOVELTY
    # -----------------------------

    TOP_K = 5
    top_matches = matches[:TOP_K]

    reference_urls = [m.url for m in top_matches]
    reference_embeddings = await asyncio.to_thread(get_embeddings_by_urls, reference_urls)

    novelty = None
    novelty_details = None

    if reference_embeddings:
        centroid = compute_centroid(reference_embeddings)
        novelty_score = compute_novelty_score(emb, centroid)

        novelty = {
            "novelty_score": round(novelty_score, 3),
            "interpretation": (
                "very new" if novelty_score > 0.6
                else "somewhat new" if novelty_score > 0.3
                else "mostly repeated"
            )
        }

    return {
        "similar_found": len(matches) > 0,
        "cluster_id": cluster_id,
        "matches": matches[:5],
        "novelty": novelty,
        "novelty_details": novelty_details
    }

@app.get("/api/history")
async def get_history(user: User = Depends(current_active_user)):
    from storage import cursor

    def _fetch():
        cursor.execute("""
            SELECT cluster_id, title, url, timestamp, similarity
            FROM articles WHERE user_id = ?
            ORDER BY timestamp ASC
        """, (str(user.id),))
        return cursor.fetchall()

    rows = await asyncio.to_thread(_fetch)

    clusters = {}
    for cluster_id, title, url, timestamp, similarity in rows:
        cid = cluster_id or url
        if cid not in clusters:
            clusters[cid] = {
                "representativeTitle": title,
                "representativeUrl": url,
                "articles": [],
                "lastVisited": timestamp,
            }
        else:
            clusters[cid]["articles"].append({
                "title": title,
                "url": url,
                "similarity": similarity or 0
            })

        if timestamp and timestamp > (clusters[cid]["lastVisited"] or ""):
            clusters[cid]["lastVisited"] = timestamp

    clusters = dict(sorted(clusters.items(), key=lambda x: x[1]["lastVisited"] or "", reverse=True))

    return {"clusters": clusters}

@app.delete("/api/history")
async def clear_history(user: User = Depends(current_active_user)):
    from storage import cursor, conn

    def _delete():
        cursor.execute("DELETE FROM articles WHERE user_id = ?", (str(user.id),))
        conn.commit()

    await asyncio.to_thread(_delete)
    return {"ok": True}

@app.get("/")
def health():
    return {"status": "ok"}


class URLRequest(BaseModel):
    url: str


@app.post("/extract-url", response_model=ArticleResponse)
async def extract_and_process_url(request: URLRequest, user: User = Depends(current_active_user)):
    """
    Extract content from URL and process it for similarity
    This endpoint combines content extraction + similarity detection
    """
    user_id = str(user.id)
    try:
        print(f"===== EXTRACTING URL FOR USER {user_id} =====")
        print(f"URL: {request.url}")
        
        # Check if this URL already exists in database
        request.url = normalize_url(request.url)
        existing = await asyncio.to_thread(get_article_by_url, request.url, user_id)
        if existing:
            print(f"===== URL ALREADY EXISTS FOR USER {user_id}: {request.url} =====")
            # Use existing embedding
            emb = existing['embedding']
            
            # Find matches (excluding self)
            titles, urls, domains, timestamps, embs = await asyncio.to_thread(load_all, user_id)
            matches = []

            now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            cur_domain = existing.get("domain", "")
            
            if embs is not None:
                sims = embs @ emb
                
                for title, url, od, ots, sim in zip(titles, urls, domains, timestamps, sims):
                    E = float(sim)
                    
                    if url == request.url:
                        continue
                
                    domain_same = 1.0 if (cur_domain and od and cur_domain == od) else 0.0
                    time_diff_days = _time_diff_days(ots, now_iso) if ots else 0.0

                    if _logreg_accept(E, domain_same, time_diff_days):
                        matches.append(
                            SimilarArticle(
                                title=title,
                                url=url,
                                similarity=E
                            )
                        )
            
            matches.sort(key=lambda x: x.similarity, reverse=True)
            candidate_urls = [request.url] + [m.url for m in matches[:5]]
            cluster_id = min(candidate_urls) if candidate_urls else request.url
            
            return {
                "similar_found": len(matches) > 0,
                "cluster_id": cluster_id,
                "matches": matches[:5],
                "extracted_article": {
                    "title": existing["title"],
                    "domain": existing.get("domain", ""),
                    "timestamp": existing.get("timestamp", None),
                }
            }
        
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
        article.url = normalize_url(article.url)
        
        print(f"Extracted: {article.title}")
        print(f"Content length: {len(article.content)}")
        
        # Process the article (same logic as /article endpoint)
        emb = engine.embed(article.title, article.content)
        
        titles, urls, domains, timestamps, embs = await asyncio.to_thread(load_all, user_id)
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

            for title, url, od, ots, sim in zip(titles, urls, domains, timestamps, sims):
                E = float(sim)
                 
                if url == article.url:
                    continue  
                    
                domain_same = 1.0 if (cur_domain and od and cur_domain == od) else 0.0
                time_diff_days = _time_diff_days(ots, now_iso) if ots else 0.0

                if _logreg_accept(E, domain_same, time_diff_days):
                    matches.append(
                        SimilarArticle(
                            title=title,
                            url=url,
                            similarity=E
                        )
                    )

        print("MAX SIMILARITY:", max_sim)

        matches.sort(key=lambda x: x.similarity, reverse=True)
        candidate_urls = [article.url] + [m.url for m in matches[:5]]
        cluster_id = min(candidate_urls) if candidate_urls else article.url

        top_similarity = matches[0].similarity if matches else None
        await asyncio.to_thread(save_article, article, emb, user_id, cluster_id=cluster_id, similarity=top_similarity)
        # -----------------------------
        # CLUSTER CENTROID NOVELTY (same as /article)
        # -----------------------------
        TOP_K = 5
        top_matches = matches[:TOP_K]

        reference_urls = [m.url for m in top_matches]
        reference_embeddings = await asyncio.to_thread(get_embeddings_by_urls, reference_urls)

        novelty = None
        novelty_details = None

        if reference_embeddings:
            centroid = compute_centroid(reference_embeddings)
            novelty_score = compute_novelty_score(emb, centroid)

            novelty = {
                "novelty_score": round(novelty_score, 3),
                "interpretation": (
                    "very new" if novelty_score > 0.6
                    else "somewhat new" if novelty_score > 0.3
                    else "mostly repeated"
                )
            }
            novelty_details = _compute_novelty_details(
                article.title, article.content, reference_urls, novelty_score
            )

        return {
            "similar_found": len(matches) > 0,
            "cluster_id": cluster_id,
            "matches": matches[:5],
            "novelty": novelty,
            "novelty_details": novelty_details,
            "extracted_article": { 
                "title": article.title,
                "domain": article.domain,
                "timestamp": article.timestamp
            }
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
