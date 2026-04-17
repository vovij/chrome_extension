import asyncio
import os
import struct
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi_users.exceptions import UserAlreadyExists
from pydantic import BaseModel

from auth import (
    User, UserCreate, UserRead,
    auth_backend, create_db_and_tables, current_active_user, fastapi_users,
)
from cluster_utils import compute_centroid, compute_novelty_score
from engine import EmbeddingEngine
from extract_content import extract_article_content
from llm_summarizer import summarize_whats_new
from models import ArticleInput, ArticleResponse, SimilarArticle
from storage import (
    assign_article_to_best_match_cluster,
    get_article_by_url, get_content_by_urls, get_embeddings_by_urls,
    load_all, normalize_url, save_article,
)
from whats_new import _split_sentences, compute_whats_new




# app setup

@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    yield


app = FastAPI(title="SeenIt API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock down to extension ID before deploying
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = EmbeddingEngine()


# error handling

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    messages = []
    for e in exc.errors():
        if e["type"] == "value_error":
            messages.append(e.get("msg", "").replace("Value error, ", ""))
        elif e["type"] == "string_too_short":
            field = e["loc"][-1] if e["loc"] else "field"
            messages.append(f"{field.capitalize()} is too short")
        elif e["type"] == "missing":
            field = e["loc"][-1] if e["loc"] else "field"
            messages.append(f"{field.capitalize()} is required")
        else:
            messages.append(e.get("msg", "Validation error"))
    return JSONResponse(
        status_code=400,
        content={"detail": ". ".join(messages) if messages else "Validation error"},
    )


# auth routes

app.include_router(
    fastapi_users.get_auth_router(auth_backend, requires_verification=True),
    prefix="/api/auth", tags=["auth"],
)
app.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/api/auth", tags=["auth"],
)
app.include_router(
    fastapi_users.get_users_router(UserRead, UserCreate),
    prefix="/api/users", tags=["users"],
)


@app.get("/api/auth/verify")
async def verify_email(token: str, user_manager=Depends(fastapi_users.get_user_manager)):
    try:
        await user_manager.verify(token)
        return {"success": True, "message": "Email verified successfully. You can now log in."}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")


class ResendVerificationRequest(BaseModel):
    email: str


@app.post("/api/auth/resend-verification", tags=["auth"])
async def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    user_manager=Depends(fastapi_users.get_user_manager),
):
    email = payload.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    try:
        user = await user_manager.get_by_email(email)
    except Exception:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_verified:
        return {"success": True, "message": "User is already verified"}
    try:
        await user_manager.request_verify(user, request)
        return {"success": True, "message": "Verification email sent"}
    except Exception as exc:
        print(f"[auth] resend verification error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to send verification email")


@app.get("/verify-email", response_class=HTMLResponse)
async def verify_email_page(token: str, user_manager=Depends(fastapi_users.get_user_manager)):
    try:
        await user_manager.verify(token, request=None)
        return "<html><body><h2>Email verified!</h2><p>You can now close this tab and use the extension.</p></body></html>"
    except Exception:
        return "<html><body><h2>Invalid or expired link</h2><p>Please request a new verification email.</p></body></html>"


@app.post("/api/register", tags=["auth"])
async def register(
    user_create: UserCreate,
    request: Request,
    user_manager=Depends(fastapi_users.get_user_manager),
):
    try:
        user = await user_manager.create(user_create, request=request)
        return {
            "success": True,
            "message": "Registration successful. Please check your email to verify your account.",
            "user": {
                "id": str(user.id),
                "email": user.email,
                "is_active": user.is_active,
                "is_verified": user.is_verified,
                "is_superuser": user.is_superuser,
            },
        }
    except UserAlreadyExists:
        raise HTTPException(status_code=400, detail="A user with this email already exists")
    except Exception as exc:
        print(f"[auth] registration error: {exc}")
        raise HTTPException(status_code=400, detail="Registration failed. Please try again.")


# similarity threshold

TAU_EMBED = float(os.getenv("SEENIT_THRESHOLD", "0.7"))



def _is_match(E: float) -> bool:
    return E >= TAU_EMBED


# shared helpers

def _bytes_to_floats(blob) -> Optional[list]:
    if blob is None:
        return None
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def _dot(a, b) -> Optional[float]:
    if not a or not b:
        return None
    return sum(x * y for x, y in zip(a, b))


def _compute_novelty_details(
    user_id: str,
    current_title: str,
    current_content: str,
    reference_urls: list,
    novelty_score: float,
) -> Optional[dict]:
    if not reference_urls:
        return None
    try:
        ref_contents = get_content_by_urls(user_id, reference_urls)
        if not ref_contents:
            return None

        result = compute_whats_new(current_title, current_content, ref_contents)
        sentences = result.get("sentences") or []

        # fall back to article lede when no novel sentences found
        if not sentences and current_content:
            sentences = _split_sentences(current_content)[:5]

        if sentences:
            try:
                llm_summary = summarize_whats_new(sentences)
                if llm_summary:
                    result["summary"] = llm_summary
            except Exception as exc:
                print(f"[SeenIt] LLM summary error: {exc}")

        result.pop("sentences", None)
        if result["new_entities"] or result["new_numbers"] or result.get("summary"):
            return result
    except Exception as exc:
        print(f"[SeenIt] whats_new error: {exc}")
    return None


async def _find_matches(user_id: str, emb, current_url: str) -> tuple:
    titles, urls, domains, timestamps, embs = await asyncio.to_thread(load_all, user_id)
    matches = []
    max_sim = None

    if embs is not None:
        sims = embs @ emb
        try:
            max_sim = float(sims.max())
        except Exception:
            pass
        print(f"[similarity] max: {max_sim:.4f}" if max_sim is not None else "[similarity] max: n/a")
        for title, url, _, __, sim in zip(titles, urls, domains, timestamps, sims):
            if normalize_url(url) == normalize_url(current_url):
                continue
            E = float(sim)
            if _is_match(E):
                matches.append(SimilarArticle(title=title, url=url, similarity=E))

    matches.sort(key=lambda x: x.similarity, reverse=True)
    return matches, max_sim


async def _assign_cluster(user_id: str, article_url: str, matches: list) -> str:
    best = matches[0] if matches else None
    return await asyncio.to_thread(
        assign_article_to_best_match_cluster,
        user_id, article_url,
        best.url if best else None,
        best.similarity if best else None,
    )


async def _build_novelty(
    *, user_id: str, article: ArticleInput, emb, matches: list, include_details: bool
) -> tuple[Optional[dict], Optional[dict]]:
    reference_urls = [m.url for m in matches[:5]]
    reference_embeddings = await asyncio.to_thread(get_embeddings_by_urls, user_id, reference_urls)

    if not reference_embeddings:
        return None, None

    centroid = compute_centroid(reference_embeddings)
    novelty_score = compute_novelty_score(emb, centroid)
    novelty = {
        "novelty_score": round(novelty_score, 3),
        "interpretation": (
            "very new" if novelty_score > 0.6
            else "somewhat new" if novelty_score > 0.3
            else "mostly repeated"
        ),
    }
    novelty_details = (
        _compute_novelty_details(user_id, article.title, article.content, reference_urls, novelty_score)
        if include_details else None
    )
    return novelty, novelty_details


async def _process_article(article: ArticleInput, user_id: str, include_novelty_details: bool) -> dict:
    article.url = normalize_url(article.url)
    existing = await asyncio.to_thread(get_article_by_url, article.url, user_id)

    if existing:
        emb = existing["embedding"]
    else:
        print(f"[embed] title: {article.title}")
        print(f"[embed] content length: {len(article.content or '')}")
        print(f"[embed] content preview: {(article.content or '')[:300]}")
        emb = engine.embed(article.title, article.content)
        await asyncio.to_thread(save_article, article, emb, user_id, cluster_id=article.url, similarity=None)

    matches, _ = await _find_matches(user_id, emb, article.url)
    cluster_id = await _assign_cluster(user_id, article.url, matches)
    novelty, novelty_details = await _build_novelty(
        user_id=user_id, article=article, emb=emb,
        matches=matches, include_details=include_novelty_details,
    )

    return {
        "similar_found": len(matches) > 0,
        "cluster_id": cluster_id,
        "matches": matches[:5],
        "novelty": novelty,
        "novelty_details": novelty_details,
    }


# article endpoints

@app.post("/article", response_model=ArticleResponse)
async def process_article(article: ArticleInput, user: User = Depends(current_active_user)):
    return await _process_article(article, str(user.id), include_novelty_details=True)


class URLRequest(BaseModel):
    url: str


@app.post("/extract-url", response_model=ArticleResponse)
async def extract_and_process_url(request: URLRequest, user: User = Depends(current_active_user)):
    user_id = str(user.id)
    try:
        request.url = normalize_url(request.url)
        extracted = await asyncio.to_thread(extract_article_content, request.url)

        if not extracted.get("title") or not extracted.get("text"):
            raise HTTPException(status_code=400, detail="Could not extract article content from URL")

        article = ArticleInput(
            title=extracted["title"],
            content=extracted["text"],
            url=request.url,
            domain=extracted.get("domain"),
            timestamp=extracted.get("timestamp"),
        )

        result = await _process_article(article, user_id, include_novelty_details=True)
        result["extracted_article"] = {
            "title": article.title,
            "domain": article.domain,
            "timestamp": article.timestamp,
        }
        return result

    except HTTPException:
        raise
    except Exception as exc:
        print(f"[SeenIt] extract-url error: {exc}")
        raise HTTPException(status_code=500, detail=f"Error processing URL: {exc}")


# history endpoints

@app.get("/api/history")
async def get_history(user: User = Depends(current_active_user)):
    from storage import cursor

    def _fetch():
        cursor.execute("""
            SELECT cluster_id, title, url, timestamp, embedding
            FROM articles WHERE user_id = ?
            ORDER BY timestamp ASC, rowid ASC
        """, (str(user.id),))
        return cursor.fetchall()

    rows = await asyncio.to_thread(_fetch)
    clusters = {}

    for cluster_id, title, url, timestamp, embedding_blob in rows:
        cid = normalize_url(cluster_id or url)
        article_obj = {
            "title": title,
            "url": normalize_url(url),
            "similarity": None,
            "timestamp": timestamp,
            "_embedding": _bytes_to_floats(embedding_blob),
        }
        if cid not in clusters:
            clusters[cid] = {
                "cluster_id": cid,
                "representativeTitle": title,
                "representativeUrl": normalize_url(url),
                "articles": [article_obj],
                "lastVisited": timestamp,
            }
        else:
            clusters[cid]["articles"].append(article_obj)
            if timestamp and timestamp > (clusters[cid]["lastVisited"] or ""):
                clusters[cid]["lastVisited"] = timestamp

    for cluster in clusters.values():
        articles = cluster["articles"]
        head_emb = articles[0].get("_embedding") if articles else None
        for article in articles:
            emb = article.pop("_embedding", None)
            article["similarity"] = _dot(head_emb, emb) if head_emb and emb else None

    return {"clusters": dict(sorted(clusters.items(), key=lambda x: x[1]["lastVisited"] or "", reverse=True))}


@app.get("/api/current-cluster")
async def get_current_cluster(url: str, user: User = Depends(current_active_user)):
    from storage import cursor

    current_url = normalize_url(url)
    existing = await asyncio.to_thread(get_article_by_url, current_url, str(user.id))

    if not existing or existing.get("embedding") is None:
        return {"cluster": None}

    current_emb = list(existing["embedding"])

    def _fetch_cluster_rows():
        cursor.execute(
            "SELECT cluster_id FROM articles WHERE user_id = ? AND url = ?",
            (str(user.id), current_url),
        )
        row = cursor.fetchone()
        if not row:
            return None, []
        cluster_id = normalize_url(row[0] or current_url)
        cursor.execute("""
            SELECT title, url, timestamp, embedding
            FROM articles WHERE user_id = ? AND cluster_id = ?
            ORDER BY timestamp ASC, rowid ASC
        """, (str(user.id), cluster_id))
        return cluster_id, cursor.fetchall()

    cluster_id, rows = await asyncio.to_thread(_fetch_cluster_rows)
    if not cluster_id:
        return {"cluster": None}

    articles = [
        {
            "title": title,
            "url": normalize_url(article_url),
            "similarity": _dot(current_emb, _bytes_to_floats(emb_blob)),
            "timestamp": timestamp,
        }
        for title, article_url, timestamp, emb_blob in rows
    ]

    representative = articles[0] if articles else None
    return {
        "cluster": {
            "cluster_id": cluster_id,
            "representativeTitle": representative["title"] if representative else "Cluster",
            "representativeUrl": representative["url"] if representative else current_url,
            "articles": articles,
            "lastVisited": max((a["timestamp"] or "" for a in articles), default=None),
        }
    }


@app.delete("/api/history")
async def clear_history(user: User = Depends(current_active_user)):
    from storage import cursor, conn

    def _delete():
        cursor.execute("DELETE FROM articles WHERE user_id = ?", (str(user.id),))
        conn.commit()

    await asyncio.to_thread(_delete)
    return {"ok": True}


@app.get("/extract-only/{url:path}")
async def extract_content_only(url: str):
    try:
        return await asyncio.to_thread(extract_article_content, url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}")


@app.get("/")
def health():
    return {"status": "ok"}