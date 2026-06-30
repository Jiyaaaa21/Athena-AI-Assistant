"""
backend/core/llm.py  —  Phase 14: Athena Personality + Context-Aware LLM

Phase 15 fixes:
- ask_llm_with_memory() NO LONGER double-writes messages. api/chat.py is the
  single source of truth for persisting conversation turns. Previously both
  this function AND chat.py called add_message(), creating duplicate history
  entries that eventually caused context corruption.
- Context builder is cached per-request (one DB round-trip per message, not
  one per LLM call).
- All existing function signatures preserved for backward compatibility.
"""

from groq import Groq
from backend.core.config import GROQ_API_KEY
from backend.core.memory_service import get_history

client = Groq(api_key=GROQ_API_KEY)

# ── Phase 14: Athena Personality System Prompt ────────────────────────────────
SYSTEM_PROMPT = """You are Athena — an intelligent, proactive, and deeply personalized AI Virtual Assistant.

PERSONALITY:
- Professional yet warm. You are sharp, context-aware, and action-oriented.
- You remember what the user has told you and connect information across sessions.
- You never respond generically when personalized context is available.
- You think like a trusted personal assistant, not a search engine.

BEHAVIOR RULES:
1. CONTEXT FIRST: If the user's goals, projects, or reminders are visible in your context, reference them naturally when relevant.
2. PROACTIVE: Occasionally surface related information the user might have forgotten (e.g., "By the way, you have a reminder for this tomorrow.").
3. ROUTING: When a user says something ambiguous like "save this" or "remind me later", use your judgment to pick the right action (note vs memory vs reminder).
4. CONTINUITY: When a user asks a follow-up question, always relate it to the prior conversation — never treat it as a fresh query.
5. PERSONALITY: You have a name (Athena), a voice, and a consistent identity. Responses feel like Athena wrote them, not a generic chatbot.
6. BREVITY: Be concise unless depth is needed. Lead with the answer, then elaborate if warranted.

CAPABILITIES (route automatically, do not ask the user which to use):
- Save notes and reminders from natural language
- Search your uploaded documents and knowledge base
- Research topics and summarize findings  
- Plan tasks and break down goals
- Answer questions using conversation history and memory

Remember: You are a Personal AI Operating System, not just a Q&A bot. Make the user feel like you know them."""

# ── Phase 15: Request-scoped context cache ────────────────────────────────────
# Stores (context_block, user_id) so we rebuild only when user changes.
_ctx_cache: dict = {}


def _build_context_system_prompt() -> str:
    """Build SYSTEM_PROMPT with live user context injected (cached per request)."""
    try:
        from backend.core.context_builder import build_user_context, format_context_for_prompt
        from backend.core.memory_intelligence import get_user_facts_prompt
        from backend.core.request_context import get_current_user_id
        uid = get_current_user_id()
        key = f"ctx_{uid}"
        if key not in _ctx_cache:
            ctx = build_user_context()
            context_block = format_context_for_prompt(ctx)
            facts_block = get_user_facts_prompt(uid) if uid else ""
            _ctx_cache[key] = context_block + facts_block
            if len(_ctx_cache) > 50:
                oldest = next(iter(_ctx_cache))
                del _ctx_cache[oldest]
        return SYSTEM_PROMPT + _ctx_cache[key]
    except Exception:
        return SYSTEM_PROMPT


def invalidate_context_cache():
    """Call after writing goals/projects/reminders so next LLM call refreshes."""
    _ctx_cache.clear()


# ── Phase 10/14: History trimming ────────────────────────────────────────────
MAX_HISTORY_MESSAGES = 12
MAX_CONTENT_CHARS = 600


def _trim_history(history: list[dict]) -> list[dict]:
    """
    Return at most MAX_HISTORY_MESSAGES recent messages, each truncated to
    MAX_CONTENT_CHARS characters, to stay within Groq's TPM limits.
    """
    recent = history[-MAX_HISTORY_MESSAGES:]
    trimmed = []
    for msg in recent:
        content = msg["content"]
        if len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS] + "…"
        trimmed.append({"role": msg["role"], "content": content})
    return trimmed


def ask_llm_raw(prompt: str) -> str:
    """One-shot LLM call with Athena personality but no memory."""
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content


def ask_llm_with_memory(user_message: str) -> str:
    """
    Context-aware call: includes full chat history + live user context.
    
    PHASE 15 FIX: No longer calls add_message() here. The caller (api/chat.py)
    is solely responsible for persisting messages, preventing duplicates.
    """
    system = _build_context_system_prompt()
    messages = [{"role": "system", "content": system}]
    messages.extend(_trim_history(get_history()))
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.7,
    )

    return response.choices[0].message.content


def ask_llm_with_context(user_message: str, extra_context: str = "") -> str:
    """
    Phase 14: Like ask_llm_with_memory but accepts an additional context
    string (e.g. from a specialist agent) merged into the system prompt.
    Does NOT persist messages — callers handle that.
    """
    system = _build_context_system_prompt()
    if extra_context:
        system = system + "\n\n" + extra_context
    messages = [{"role": "system", "content": system}]
    messages.extend(_trim_history(get_history()))
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.7,
    )
    return response.choices[0].message.content


# ── Streaming variants ────────────────────────────────────────────────────────

def ask_llm_raw_stream(prompt: str):
    """Streaming one-shot call. Yields text chunks. Does NOT persist."""
    stream = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.7,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def ask_llm_with_memory_stream(user_message: str):
    """
    Streaming context-aware call. Yields text chunks.
    Does NOT persist — caller (api/chat.py) handles add_message() after done.
    """
    system = _build_context_system_prompt()
    messages = [{"role": "system", "content": system}]
    messages.extend(_trim_history(get_history()))
    messages.append({"role": "user", "content": user_message})

    stream = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.7,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
