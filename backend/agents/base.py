"""
agents/base.py  —  Phase 13: Base class for all Athena specialist agents.
Phase 15 fix: Added get_conversation_context() so every agent can access
the last N turns of conversation history. Previously ALL agents used
ask_llm_raw() (zero history), causing catastrophic context loss on short
follow-ups like "lets start with phase 1" or "i would like to start with
the basics" — the agent had no idea what topic was being discussed.

Every agent exposes:
  - name          : str  — unique identifier used by the orchestrator
  - description   : str  — shown to the router LLM so it can decide routing
  - can_handle()  : fast heuristic pre-filter (avoids an LLM call)
  - run()         : executes the agent, returns AgentResult
  - run_stream()  : generator variant for SSE streaming
  - get_conversation_context() : returns formatted recent history string
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generator


@dataclass
class AgentResult:
    """Structured return value from every agent."""
    answer: str
    agent_name: str
    sources: list[dict] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    confidence: int = 80
    metadata: dict = field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base for all Phase 13 specialist agents."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    def can_handle(self, query: str) -> bool:
        return False

    @abstractmethod
    def run(self, query: str, context: dict | None = None) -> AgentResult: ...

    def run_stream(
        self, query: str, context: dict | None = None
    ) -> Generator[str, None, AgentResult]:
        result = self.run(query, context)
        words = result.answer.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
        return result

    # ── Phase 15: Conversation context helper ─────────────────────────────────

    def get_conversation_context(self, turns: int = 6) -> str:
        """
        Returns the last `turns` messages from the conversation as a
        formatted string block, ready to inject into any agent prompt.

        This is the core fix for the context-loss bug: agents previously
        called ask_llm_raw(prompt_built_from_query_only), which meant a
        4-word follow-up like "lets start with phase 1" arrived with zero
        context. Now every agent can call this and prepend the result to
        their prompt so the LLM understands what topic is being continued.

        Usage in a subclass prompt builder:
            history = self.get_conversation_context()
            prompt = f"{history}\\n\\nUser request: {query}\\n\\n..."
        """
        try:
            from backend.core.memory_service import get_history
            history = get_history()
            if not history:
                return ""
            recent = history[-turns:]
            lines = ["\n--- Recent conversation (use this to understand context) ---"]
            for msg in recent:
                role = "User" if msg["role"] == "user" else "Athena"
                content = (msg["content"] or "")[:300]
                lines.append(f"{role}: {content}")
            lines.append("--- End of conversation context ---\n")
            return "\n".join(lines)
        except Exception:
            return ""

    def build_context_aware_prompt(self, query: str, agent_prompt: str) -> str:
        """
        Prepends recent conversation history to any agent-specific prompt.
        Call this instead of building prompts from `query` alone.

        Example:
            prompt = self.build_context_aware_prompt(query, self._plan_prompt(query))
        """
        history_block = self.get_conversation_context()
        if not history_block:
            return agent_prompt
        return f"{history_block}\n{agent_prompt}"
