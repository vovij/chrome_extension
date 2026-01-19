from fastapi import FastAPI
from models import ArticleInput, ArticleResponse, SimilarArticle
from engine import EmbeddingEngine
from storage import save_article, load_all
import time

app = FastAPI(title="SeenIt API")

engine = EmbeddingEngine()


@app.post("/article", response_model=ArticleResponse)
async def process_article(article: ArticleInput):
    start = time.time()

    print("===== TEXT TO EMBED =====")
    print(article.title)
    print(article.content[:500])
    print("CONTENT LENGTH:", len(article.content))

    emb = engine.embed(article.title, article.content)

    titles, urls, embs = load_all()
    matches = []

    if embs is not None:
        sims = embs @ emb
        for title, url, sim in zip(titles, urls, sims):
            if sim > 0.7:
                matches.append(
                    SimilarArticle(
                        title=title,
                        url=url,
                        similarity=float(sim)
                    )
                )

    save_article(article, emb)

    max_sim = float(sims.max()) if embs is not None and len(titles) > 0 else 0.0
    print("MAX SIMILARITY:", max_sim)
    
    matches.sort(key=lambda x: x.similarity, reverse=True)
    
    if matches:
        cluster_id = matches[0].url
    else:
        cluster_id = article.url

    # ---------- RETURN ----------
    return {
        "similar_found": len(matches) > 0,
        "cluster_id": cluster_id,
        "matches": matches[:5]
    }


@app.get("/")
def health():
    return {"status": "ok"}
