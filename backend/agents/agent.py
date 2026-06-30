"""
agents/agent.py  —  Phase 13: Legacy shim → Orchestrator

process_query() signature is unchanged so callers (GET /chat) need
zero edits. Internally it now delegates to the Phase 13 orchestrator.
"""

from backend.agents.orchestrator import route_and_run


def process_query(user_query: str):
    """
    Returns (answer: str, sources: list[dict]).
    Unchanged signature — used by GET /chat (non-streaming path).
    """
    result = route_and_run(user_query)
    return result.answer, result.sources