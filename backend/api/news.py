import hashlib

import requests
from fastapi import APIRouter, HTTPException

from backend.core.config import GNEWS_API_KEY

router = APIRouter()

SEARCH_URL = "https://gnews.io/api/v4/search"
TOP_HEADLINES_URL = "https://gnews.io/api/v4/top-headlines"

# The frontend's category tabs are: all, ai, technology, business.
# GNews' /top-headlines supports a fixed category set (general, business,
# technology, ...) but has no "ai" category, so that one is handled via a
# /search query instead. "all" maps to the general top-headlines feed.
TOP_HEADLINE_CATEGORIES = {"all": "general", "business": "business", "technology": "technology"}
SEARCH_QUERIES = {"ai": "artificial intelligence"}


def _stable_id(article: dict) -> str:
    url = article.get("url", "")
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]


def _serialize(article: dict, category: str) -> dict:
    return {
        "id": _stable_id(article),
        "title": article.get("title", "Untitled"),
        "source": article.get("source", {}).get("name", "Unknown Source"),
        "publishedAt": article.get("publishedAt", ""),
        "category": category,
        "url": article.get("url", "#"),
        "summary": article.get("description") or "",
    }


@router.get("/news")
def get_news(category: str | None = None):

    if not GNEWS_API_KEY:
        raise HTTPException(status_code=503, detail="GNEWS_API_KEY is not configured on the server")

    category = (category or "all").lower()

    try:
        if category in SEARCH_QUERIES:
            response = requests.get(
                SEARCH_URL,
                params={
                    "q": SEARCH_QUERIES[category],
                    "lang": "en",
                    "max": 10,
                    "apikey": GNEWS_API_KEY,
                },
                timeout=10,
            )
        else:
            response = requests.get(
                TOP_HEADLINES_URL,
                params={
                    "category": TOP_HEADLINE_CATEGORIES.get(category, "general"),
                    "lang": "en",
                    "max": 10,
                    "apikey": GNEWS_API_KEY,
                },
                timeout=10,
            )

        data = response.json()

    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"News provider error: {e}")

    if "articles" not in data:
        # GNews error bodies look like {"errors": [...]}
        detail = data.get("errors") or "No articles returned"
        raise HTTPException(status_code=502, detail=str(detail))

    seen_urls = set()
    results = []

    for article in data["articles"]:
        url = article.get("url")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        results.append(_serialize(article, category))

    return results