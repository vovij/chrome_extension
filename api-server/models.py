from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ArticleInput(BaseModel):
    title: str
    content: str
    url: str
    domain: Optional[str] = None
    timestamp: Optional[str] = None


class SimilarArticle(BaseModel):
    title: str
    url: str
    similarity: float


class NoveltyReport(BaseModel):
    novelty_score: float
    interpretation: str


class ArticleResponse(BaseModel):
    similar_found: bool
    cluster_id: str
    matches: List[SimilarArticle]
    extracted_article: Optional[Dict[str, Any]] = None
    novelty: Optional[NoveltyReport] = None
