"""
agents/web_search_agent.py  —  Phase 15 fix v2

Fixes:
1. _is_weather_query() now uses conversation history — so a bare city
   name like "Gurgaon" as a follow-up to "what is the weather?" correctly
   resolves as a weather query instead of falling to the news path.

2. _synthesis_prompt() now explicitly tells the LLM:
   "The weather data below is REAL and LIVE. Do not say you don't have
   real-time access — you DO, it's in the data block below."
   Previously the LLM was ignoring the tool output and hallucinating a
   disclaimer saying it had no real-time access.

3. WeatherTool failure is handled gracefully — falls back to news search
   on the same topic rather than returning an unhelpful error.
"""

from __future__ import annotations

from typing import Generator

from backend.agents.base import BaseAgent, AgentResult
from backend.core.llm import ask_llm_raw, ask_llm_raw_stream
from backend.core.logger import agent_logger
from backend.tools.news import NewsTool
from backend.tools.weather import WeatherTool
from backend.tools.web_search_tool import WebSearchTool

_news_tool = NewsTool()
_weather_tool = WeatherTool()
_web_tool = WebSearchTool()

_WEB_KEYWORDS = {
    "news", "latest", "current", "today", "happening", "recent",
    "update", "headlines", "what's new", "trending", "breaking",
    "announcement", "event", "events", "weather", "temperature",
    "search for", "look up", "find information",
}

_WEATHER_KEYWORDS = ("weather", "temperature", "humidity", "forecast", "rain",
                     "hot", "cold", "sunny", "cloudy", "wind", "climate today")

# Phase 27 addition: previously this agent treated every non-weather query
# as a news search (NewsTool wraps GNews headlines specifically), so a
# question like "what's the current exchange rate for USD to INR" or "who
# won the match yesterday" got routed through a headlines API that had no
# chance of answering it, and the LLM either hallucinated or gave up.
# This narrower keyword set identifies queries that are actually asking
# for news/headlines specifically; anything else that reached this agent
# (i.e. matched _WEB_KEYWORDS but isn't weather or news-shaped) now goes
# through general web search (WebSearchTool) instead.
_NEWS_KEYWORDS = (
    "news", "headlines", "breaking", "trending", "announcement",
    "what's new", "latest on", "recent news",
)


class WebSearchAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Live web search agent. Use for current news, recent events, "
            "live weather, breaking stories, or any query requiring up-to-date "
            "information beyond the knowledge base."
        )

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in _WEB_KEYWORDS)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_weather_query(self, query: str) -> bool:
        """
        Phase 15 fix: also check conversation history so a bare city name
        like 'Gurgaon' as a follow-up to 'what is the weather?' is
        correctly classified as a weather query.
        """
        q = query.lower()
        if any(w in q for w in _WEATHER_KEYWORDS):
            return True
        # Check if the last assistant/user message was about weather
        try:
            from backend.core.memory_service import get_history
            history = get_history()
            recent = history[-4:] if history else []
            for msg in reversed(recent):
                content = msg.get("content", "").lower()
                if any(w in content for w in _WEATHER_KEYWORDS):
                    return True
        except Exception:
            pass
        return False

    def _extract_city(self, query: str) -> str:
        from backend.core.memory_service import get_history
        history = get_history()
        recent = history[-6:] if history else []
        context = ""
        if recent:
            context = "\n\nRecent conversation:\n" + "\n".join(
                f"{m['role'].capitalize()}: {m['content'][:150]}" for m in recent
            )
        prompt = (
            f"Extract only the city name from this query or conversation context. "
            f"If the query IS a city name (e.g. 'Gurgaon', 'Delhi'), return it directly. "
            f"Return ONLY the city name, nothing else.{context}\n\nQuery: {query}"
        )
        city = ask_llm_raw(prompt).strip()
        # Clean up common LLM artifacts
        for junk in ["The city is ", "City: ", ".", ","]:
            city = city.replace(junk, "").strip()
        return city

    def _extract_topic(self, query: str) -> str:
        prompt = (
            f"Extract the main search topic from this query (2-4 words max). "
            f"Return ONLY the topic, nothing else.\n\nQuery: {query}"
        )
        return ask_llm_raw(prompt).strip()

    def _weather_synthesis_prompt(self, query: str, city: str, raw_data: str) -> str:
        history = self.get_conversation_context(turns=4)
        return (
            f"You are Athena. You have LIVE, REAL-TIME weather data fetched right now.\n\n"
            f"{history}"
            f"User asked: {query}\n"
            f"City resolved: {city}\n\n"
            f"=== LIVE WEATHER DATA (fetched this moment) ===\n"
            f"{raw_data}\n"
            f"=== END WEATHER DATA ===\n\n"
            f"CRITICAL INSTRUCTIONS:\n"
            f"- The data above is real and current. Do NOT say you lack real-time access.\n"
            f"- Do NOT say you cannot provide weather — the data is right there.\n"
            f"- Present the weather naturally and conversationally.\n"
            f"- Include temperature, condition, feels-like, humidity.\n"
            f"- Add a brief practical note (e.g. 'good day to stay indoors', "
            f"'carry an umbrella', 'great weather for a walk').\n"
            f"- Keep it concise — 3-5 sentences."
        )

    def _is_news_query(self, query: str) -> bool:
        """Narrower than can_handle()'s _WEB_KEYWORDS match -- distinguishes
        an actual news/headlines request from a general factual query that
        merely matched a broad trigger word like 'current' or 'latest'."""
        q = query.lower()
        return any(kw in q for kw in _NEWS_KEYWORDS)

    def _news_synthesis_prompt(self, query: str, raw_data: str) -> str:
        history = self.get_conversation_context(turns=4)
        return (
            f"You are Athena, a knowledgeable assistant with access to live news.\n\n"
            f"{history}"
            f"User Query: {query}\n\n"
            f"Live News Data:\n{raw_data}\n\n"
            f"Provide a clear, well-organised response that:\n"
            f"1. Directly answers the user's question\n"
            f"2. Highlights the most important/relevant stories\n"
            f"3. Adds helpful context or analysis\n"
            f"4. If this is a follow-up to a prior topic, acknowledge the continuity."
        )

    def _web_search_synthesis_prompt(self, query: str, raw_data: str) -> str:
        history = self.get_conversation_context(turns=4)
        return (
            f"You are Athena. You have LIVE web search results fetched right now "
            f"for this query.\n\n"
            f"{history}"
            f"User asked: {query}\n\n"
            f"=== LIVE WEB SEARCH RESULTS (fetched this moment) ===\n"
            f"{raw_data}\n"
            f"=== END WEB SEARCH RESULTS ===\n\n"
            f"CRITICAL INSTRUCTIONS:\n"
            f"- The results above are real and current. Do NOT say you lack "
            f"real-time web access — you just searched the web, it's right there.\n"
            f"- Answer the user's question directly using the results.\n"
            f"- If the results don't actually answer the question, say so honestly "
            f"rather than guessing — don't fabricate an answer the results don't support.\n"
            f"- Cite which result a specific claim came from when it matters "
            f"(e.g. 'according to [source]')."
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, query: str, context: dict | None = None) -> AgentResult:
        steps = []
        agent_logger.info(f"[WebSearchAgent] query={query!r}")

        if self._is_weather_query(query):
            steps.append("Detected weather query…")
            city = self._extract_city(query)
            steps.append(f"City resolved: '{city}'")

            raw = _weather_tool.run(city)
            steps.append("Fetched live weather data")

            # If weather tool failed, fall back to news
            if "not found" in raw.lower() or "failed" in raw.lower() or "not specified" in raw.lower():
                steps.append(f"Weather lookup failed, trying news fallback…")
                raw_news = _news_tool.run(f"weather {city}")
                prompt = self._news_synthesis_prompt(query, raw_news)
                answer = ask_llm_raw(prompt)
            else:
                prompt = self._weather_synthesis_prompt(query, city, raw)
                answer = ask_llm_raw(prompt)

            return AgentResult(
                answer=answer,
                agent_name=self.name,
                sources=[],
                steps=steps,
                confidence=85,
                metadata={"query_type": "weather", "city": city},
            )

        if self._is_news_query(query):
            steps.append("Extracting search topic…")
            topic = self._extract_topic(query)
            steps.append(f"Searching news: '{topic}'…")
            raw = _news_tool.run(topic)
            if not raw.strip() or "error" in raw.lower():
                raw = _news_tool.run(query[:60])
            steps.append("Synthesising results…")
            prompt = self._news_synthesis_prompt(query, raw)
            answer = ask_llm_raw(prompt)

            return AgentResult(
                answer=answer,
                agent_name=self.name,
                sources=[],
                steps=steps,
                confidence=78,
                metadata={"query_type": "news"},
            )

        # Phase 27 addition: general web search — everything that reached
        # this agent but isn't weather or a genuine news/headlines request.
        # Previously this fell through to the news path above, running a
        # GNews headline search for questions that had nothing to do with
        # headlines (e.g. "what's the current price of X").
        steps.append("Searching the web…")
        raw = _web_tool.run(query)
        steps.append("Synthesising results…")
        prompt = self._web_search_synthesis_prompt(query, raw)
        answer = ask_llm_raw(prompt)

        return AgentResult(
            answer=answer,
            agent_name=self.name,
            sources=[],
            steps=steps,
            confidence=80,
            metadata={"query_type": "web_search"},
        )

    def run_stream(
        self, query: str, context: dict | None = None
    ) -> Generator[str, None, None]:
        agent_logger.info(f"[WebSearchAgent] stream query={query!r}")

        if self._is_weather_query(query):
            city = self._extract_city(query)
            raw = _weather_tool.run(city)
            if "not found" in raw.lower() or "failed" in raw.lower():
                raw = _news_tool.run(f"weather {city}")
                prompt = self._news_synthesis_prompt(query, raw)
            else:
                prompt = self._weather_synthesis_prompt(query, city, raw)
        else:
            if self._is_news_query(query):
                topic = self._extract_topic(query)
                raw = _news_tool.run(topic)
                prompt = self._news_synthesis_prompt(query, raw)
            else:
                # Phase 27 addition: see run() for why general queries no
                # longer fall through to a news-headlines search.
                raw = _web_tool.run(query)
                prompt = self._web_search_synthesis_prompt(query, raw)

        for chunk in ask_llm_raw_stream(prompt):
            yield chunk