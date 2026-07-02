import requests

from backend.core.config import TAVILY_API_KEY


class WebSearchTool:
    """
    Phase 27 addition: general-purpose web search.

    Before this, backend/tools/ only had NewsTool (GNews headlines) and
    WeatherTool -- WebSearchAgent and ResearchAgent both routed *every*
    "search the web" style question through one of those two, meaning
    Athena had no way to actually answer something like "what's the
    current exchange rate for X" or "who won [event]" unless it happened
    to be recent-news-shaped. This wraps Tavily's search API, which is
    purpose-built for feeding LLM agents clean, pre-summarized results
    (title + snippet + URL, sometimes a synthesized short answer) rather
    than raw search-engine HTML to parse.

    Mirrors NewsTool's interface (a `.run(query)` method returning a
    plain-text block ready to drop into an LLM prompt, or a short error
    string on failure) so it slots into the existing agent code the same
    way NewsTool/WeatherTool already do.
    """

    name = "web_search"

    description = (
        "Search the open web for current information on any topic -- "
        "not limited to news headlines or weather. Use for factual "
        "lookups, current prices/stats, 'who/what/when' questions about "
        "recent or general topics, and anything else that needs a live "
        "answer from beyond the knowledge base."
    )

    def run(self, query: str) -> str:
        if not TAVILY_API_KEY:
            return (
                "Web search error: TAVILY_API_KEY is not configured. "
                "Get a free key (no credit card, 1,000 searches/month) at "
                "https://tavily.com and set TAVILY_API_KEY."
            )

        try:
            response = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": TAVILY_API_KEY,
                    "query": query,
                    "search_depth": "basic",  # 1 credit/search vs 2 for "advanced"
                    "include_answer": True,
                    "max_results": 5,
                },
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            return f"Web search error: {e}"

        parts: list[str] = []

        # Tavily's own synthesized short answer, when it has enough
        # confidence to produce one -- often the fastest path to a
        # grounded response for a straightforward factual query.
        direct_answer = data.get("answer")
        if direct_answer:
            parts.append(f"Direct answer: {direct_answer}\n")

        results = data.get("results", [])
        if not results and not direct_answer:
            return "No web search results found."

        for i, result in enumerate(results, start=1):
            title = result.get("title", "Untitled")
            url = result.get("url", "")
            content = (result.get("content") or "").strip()
            # Tavily's "content" field can run long; keep the prompt lean.
            if len(content) > 500:
                content = content[:500] + "…"
            parts.append(f"{i}. {title}\n{content}\nURL: {url}\n")

        return "\n".join(parts)