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

from __future__ import annotations

from typing import Generator

from groq import Groq
from backend.core.config import GROQ_API_KEY, GEMINI_API_KEY
from backend.core.memory_service import get_history
from backend.core.logger import error_logger

client = Groq(api_key=GROQ_API_KEY)

# ── Phase 26: free fallback provider ──────────────────────────────────────────
#
# Groq's free tier has fairly tight per-model TPM/RPD token limits. Once
# those are hit mid-session, every _groq_complete()/_groq_complete_stream()
# call below started raising (a 429 from the Groq SDK) and the whole app
# went down with it -- every chat message, every agent, every "conversational
# response" fallback path all route through this one module.
#
# Fix: on ANY Groq failure (rate limit, quota exhausted, transient outage,
# auth issue, whatever), transparently retry the same request against
# Google's Gemini API instead, which also has a genuinely free tier (no
# credit card required -- https://aistudio.google.com/apikey) with its own,
# separate quota. Implemented as a raw REST call via `requests` (already a
# dependency) rather than pulling in the google-generativeai SDK, to avoid
# adding a new dependency just for this.
#
# This is a fallback, not a primary provider: Groq is tried first on every
# call, every time, and Gemini is only ever touched when Groq has already
# failed. If GEMINI_API_KEY isn't set, the app behaves exactly as before
# (Groq failures surface as errors) -- the fallback is purely additive.
import json
import requests

_GEMINI_MODEL = "gemini-2.0-flash"
_GEMINI_BASE = f"https://generativelanguage.googleapis.com/v1beta/models/{_GEMINI_MODEL}"


def _messages_to_gemini(messages: list[dict]) -> tuple[str, list[dict]]:
    """OpenAI-style [{role, content}, ...] -> Gemini's (systemInstruction text, contents[])."""
    system_parts = []
    contents = []
    for m in messages:
        if m["role"] == "system":
            system_parts.append(m["content"])
        elif m["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": m["content"]}]})
        else:  # "user" (and anything unrecognized defaults to user turn)
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
    return "\n\n".join(system_parts), contents


def _gemini_payload(messages: list[dict]) -> dict:
    system_text, contents = _messages_to_gemini(messages)
    payload: dict = {
        "contents": contents,
        "generationConfig": {"temperature": _SAMPLING_PARAMS["temperature"]},
    }
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text}]}
    return payload


def _gemini_complete(messages: list[dict]) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("Groq failed and GEMINI_API_KEY is not configured — no fallback available.")
    resp = requests.post(
        f"{_GEMINI_BASE}:generateContent",
        headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        json=_gemini_payload(messages),
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _parse_gemini_sse(resp) -> Generator[str, None, None]:
    """Shared SSE-chunk parser for both the text-fallback stream and the
    vision stream below -- keeping this in one place means a fix to how
    Gemini's stream is parsed only has to happen once."""
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        raw = line[len("data: "):].strip()
        if raw == "[DONE]":
            break
        try:
            chunk = json.loads(raw)
            text = chunk["candidates"][0]["content"]["parts"][0].get("text", "")
        except (KeyError, IndexError, json.JSONDecodeError):
            continue
        if text:
            yield text


def _gemini_complete_stream(messages: list[dict]):
    if not GEMINI_API_KEY:
        yield (
            "I'm having trouble reaching the AI service right now — both the "
            "primary and fallback providers are unavailable. Please try again "
            "shortly."
        )
        return
    with requests.post(
        f"{_GEMINI_BASE}:streamGenerateContent?alt=sse",
        headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        json=_gemini_payload(messages),
        timeout=120,
        stream=True,
    ) as resp:
        resp.raise_for_status()
        yield from _parse_gemini_sse(resp)


# ── Phase 28: image understanding ─────────────────────────────────────────────
#
# Uploading an image in the composer previously did nothing beyond showing a
# local preview -- the actual bytes never reached the LLM. The text sent to
# the backend was just a placeholder like "Please analyze this image:
# photo.jpg", with no visual data attached at all, so any answer was either
# an admission it couldn't see the image or an outright hallucination.
#
# This routes image-bearing messages through Gemini specifically, not Groq.
# Groq does have vision-capable models, but its lineup has been through
# repeated deprecation churn recently (Llama 4 Scout and Maverick both
# deprecated in favor of openai/gpt-oss-120b), and that replacement model is
# confirmed NOT to accept image input on Groq at all (returns "messages[1]
# .content must be a string" for a multimodal request). Guessing at whichever
# Groq vision model happens to be current risks a confusing failure; Gemini's
# multimodal support is stable and well-documented, so images always go
# there, independent of whatever text model Groq happens to be serving.

_SUPPORTED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


def _parse_data_uri(data_uri: str) -> tuple[str, str] | None:
    """'data:image/png;base64,AAAA...' -> ('image/png', 'AAAA...'). None if malformed."""
    if not data_uri or not data_uri.startswith("data:") or "," not in data_uri:
        return None
    header, b64data = data_uri.split(",", 1)
    mime_type = header[len("data:"):].split(";")[0].strip().lower()
    if not mime_type or not b64data:
        return None
    return mime_type, b64data


def _gemini_vision_payload(messages: list[dict], image_data_uri: str) -> dict | None:
    """Returns None if the image couldn't be parsed -- caller shows a clean
    error rather than sending a malformed request to Gemini."""
    parsed = _parse_data_uri(image_data_uri)
    if not parsed:
        return None
    mime_type, b64data = parsed

    system_text, contents = _messages_to_gemini(messages)
    image_part = {"inline_data": {"mime_type": mime_type, "data": b64data}}
    # Attach the image to the current (last) user turn specifically, not
    # spread across history -- images aren't persisted long-term (see
    # note in api/chat.py), so only the turn that actually carries one
    # should claim to have it.
    if contents and contents[-1]["role"] == "user":
        contents[-1]["parts"].append(image_part)
    else:
        contents.append({"role": "user", "parts": [image_part]})

    payload: dict = {
        "contents": contents,
        "generationConfig": {"temperature": _SAMPLING_PARAMS["temperature"]},
    }
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text}]}
    return payload


def _unsupported_image_message(mime_type: str | None) -> str:
    if mime_type == "image/gif":
        return (
            "I can't analyze GIFs yet — only PNG, JPEG, and WebP images are "
            "supported for image understanding right now. If it's a single "
            "frame you want analyzed, try saving it as a PNG or JPEG first."
        )
    return (
        f"I can't analyze that image format ({mime_type or 'unrecognized'}) — "
        f"PNG, JPEG, and WebP are supported."
    )


def _build_vision_messages(user_message: str) -> list[dict]:
    system = _build_context_system_prompt()
    messages = [{"role": "system", "content": system}]
    messages.extend(_trim_history(get_history()))
    messages.append({"role": "user", "content": user_message or "What's in this image?"})
    return messages


_NO_VISION_PROVIDER_MESSAGE = (
    "I can't analyze images right now — image understanding requires a "
    "GEMINI_API_KEY to be configured on the server (Groq, the primary "
    "provider, doesn't support image input on this deployment). Free, no "
    "credit card: https://aistudio.google.com/apikey."
)


def ask_llm_with_image(user_message: str, image_data_uri: str) -> str:
    """Non-streaming image understanding. Always via Gemini -- see module
    note above for why Groq is deliberately not attempted for vision."""
    if not GEMINI_API_KEY:
        return _NO_VISION_PROVIDER_MESSAGE

    parsed = _parse_data_uri(image_data_uri)
    if not parsed:
        return "I couldn't read that image — the file may be corrupted or in an unsupported format."
    mime_type, _ = parsed
    if mime_type not in _SUPPORTED_IMAGE_MIME_TYPES:
        return _unsupported_image_message(mime_type)

    messages = _build_vision_messages(user_message)
    payload = _gemini_vision_payload(messages, image_data_uri)
    if payload is None:
        return "I couldn't read that image — the file may be corrupted or in an unsupported format."

    try:
        resp = requests.post(
            f"{_GEMINI_BASE}:generateContent",
            headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        error_logger.error(f"[llm] Vision request failed: {e}")
        return "I had trouble analyzing that image just now. Please try again in a moment."


def ask_llm_with_image_stream(user_message: str, image_data_uri: str):
    """Streaming image understanding. Always via Gemini -- see module note
    above for why Groq is deliberately not attempted for vision."""
    if not GEMINI_API_KEY:
        yield _NO_VISION_PROVIDER_MESSAGE
        return

    parsed = _parse_data_uri(image_data_uri)
    if not parsed:
        yield "I couldn't read that image — the file may be corrupted or in an unsupported format."
        return
    mime_type, _ = parsed
    if mime_type not in _SUPPORTED_IMAGE_MIME_TYPES:
        yield _unsupported_image_message(mime_type)
        return

    messages = _build_vision_messages(user_message)
    payload = _gemini_vision_payload(messages, image_data_uri)
    if payload is None:
        yield "I couldn't read that image — the file may be corrupted or in an unsupported format."
        return

    try:
        with requests.post(
            f"{_GEMINI_BASE}:streamGenerateContent?alt=sse",
            headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=120,
            stream=True,
        ) as resp:
            resp.raise_for_status()
            yielded_any = False
            for chunk in _parse_gemini_sse(resp):
                yielded_any = True
                yield chunk
            if not yielded_any:
                yield (
                    "I looked at the image but couldn't come up with a response — "
                    "try asking again, maybe with a more specific question."
                )
    except Exception as e:
        error_logger.error(f"[llm] Vision stream request failed: {e}")
        yield "I had trouble analyzing that image just now. Please try again in a moment."


def _groq_complete(messages: list[dict]) -> str:
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        **_SAMPLING_PARAMS,
    )
    return response.choices[0].message.content


def _groq_complete_stream(messages: list[dict]):
    stream = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        **_SAMPLING_PARAMS,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


_BOTH_PROVIDERS_FAILED_MESSAGE = (
    "I'm having trouble reaching the AI service right now -- both the "
    "primary and fallback providers are unavailable. Please try again "
    "in a moment."
)


def _complete(messages: list[dict]) -> str:
    """Try Groq; on any failure, fall back to Gemini. If Gemini also
    fails, never let that raw exception (potentially containing request
    details we don't want surfaced to the user) become the visible
    answer -- log it and return a clean, generic message instead."""
    try:
        return _groq_complete(messages)
    except Exception as e:
        error_logger.warning(f"[llm] Groq call failed ({e}); falling back to Gemini.")
        try:
            return _gemini_complete(messages)
        except Exception as e2:
            error_logger.error(f"[llm] Gemini fallback also failed ({e2}).")
            return _BOTH_PROVIDERS_FAILED_MESSAGE


def _complete_stream(messages: list[dict]):
    """
    Try Groq; on any failure, fall back to Gemini -- but only if Groq
    failed before yielding anything. Groq typically raises (a 429, etc.)
    on the initial request before streaming starts, which is exactly the
    "hit the token/rate limit" case this exists for, so this covers it
    cleanly. If Groq had already streamed part of a response and then
    failed mid-stream, restarting on Gemini would produce a garbled
    two-provider answer, so that (rarer) case just stops rather than
    switching providers mid-response.

    If Gemini's fallback attempt *also* fails, that exception is caught
    here too rather than left to propagate -- letting it bubble up would
    have it displayed to the user as raw exception text by chat.py's SSE
    error handler (str(exc)), which is exactly how a Gemini request URL
    ended up visible in a chat response before the x-goog-api-key header
    fix above. Log the real error, show a clean one.
    """
    yielded_any = False
    try:
        for chunk in _groq_complete_stream(messages):
            yielded_any = True
            yield chunk
    except Exception as e:
        if yielded_any:
            error_logger.error(f"[llm] Groq stream failed mid-response ({e}); not restarting on Gemini.")
            return
        error_logger.warning(f"[llm] Groq stream call failed ({e}); falling back to Gemini.")
        gemini_yielded_any = False
        try:
            for chunk in _gemini_complete_stream(messages):
                gemini_yielded_any = True
                yield chunk
        except Exception as e2:
            error_logger.error(f"[llm] Gemini fallback stream also failed ({e2}).")
            if not gemini_yielded_any:
                yield _BOTH_PROVIDERS_FAILED_MESSAGE

# Phase 24 tuning: every call below used to hardcode temperature=0.7 with no
# other sampling controls at all. Two concrete, mechanical additions on top
# of the prompt-level tone/length rules above:
#   - temperature 0.7 -> 0.6: still has room for natural phrasing variety,
#     but noticeably reduces rambling/tangents on a model that, left at the
#     default, tends to wander further off the direct answer than Claude or
#     GPT-4 would at the same setting.
#   - frequency_penalty=0.3 / presence_penalty=0.1: a small mechanical
#     backstop against the exact failure mode rule 7 above targets in
#     prose — repeating the same filler phrase or transition word multiple
#     times in one response. The prompt rule handles this most of the time;
#     this catches it even when the model doesn't fully comply.
# Deliberately NOT setting max_tokens here -- a hard cap risks truncating a
# legitimately long answer mid-sentence, which is a worse failure than
# occasionally running a little long. Length is handled by the prompt
# rules, not a hard ceiling.
_SAMPLING_PARAMS = {
    "temperature": 0.6,
    "frequency_penalty": 0.3,
    "presence_penalty": 0.1,
}

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
6. ADAPTIVE LENGTH & FORMAT: Match your response to what the question actually needs — don't default to the same long, structured answer for everything.
   - A quick fact, a yes/no, a simple how-to, or casual conversation gets a few direct sentences. No headings, no bullet list, no "summary" section — that's padding for something this simple.
   - Only reach for headings, numbered steps, or bullet lists when the content genuinely has multiple distinct parts that benefit from that structure (e.g. a real comparison, a multi-step process, several unrelated items).
   - Lead with the actual answer first, then add supporting detail only if it's warranted — never bury the point under preamble.
   - When in doubt, answer shorter. It's easy for the user to ask you to go deeper; it's tedious for them to read a long structured brief for something that needed one sentence.
7. NATURAL TONE, NOT AI-BOILERPLATE: Write the way a sharp, direct person would talk, not the way a generic chatbot fills space.
   - Never open with throat-clearing like "Great question!", "Certainly!", "I'd be happy to help you with that", or "Sure, here's...". Just answer.
   - Never close with padding like "Let me know if you have any other questions!" or "I hope this helps!" unless it's genuinely natural in that specific moment — most of the time, just stop when the answer is done.
   - Don't restate the user's question back to them before answering ("You're asking about X, so here's...") — they know what they asked.
   - Default to plain prose paragraphs for conversational answers. Markdown (headers, bold, bullets) is a tool for genuinely structured or reference content, not decoration to make an answer look thorough.
   - Vary your sentence structure and openers — don't fall into repeating the same sentence pattern across every response.
   - Have an actual opinion when asked for one, and be willing to disagree or push back when warranted. Constant agreement and hedging reads as evasive, not helpful.
   - Avoid stacking unnecessary caveats and disclaimers. State things directly; add a caveat only when it changes what the user should actually do with the answer.
8. NO SYCOPHANCY: Don't open by praising the user's question or idea ("Great idea!", "That's a smart approach!", "Excellent question!"). Don't validate something just because they said it — if an idea has a real flaw, say so plainly and constructively. Compliments should be rare and specific, never a reflexive opener.
9. HONESTY OVER CONFIDENCE: If you don't actually know something, or you're inferring rather than certain, say so directly ("I'm not sure, but..." / "I don't have that information") instead of guessing and presenting it as fact. Never fabricate a specific number, date, name, or fact to sound complete — a real "I don't know" is more useful than a confident wrong answer.
10. FORMATTING MECHANICS (when structure IS warranted):
   - Use a numbered list only when order/sequence actually matters (steps to follow, ranked items). Use bullets for a set of parallel items with no inherent order. Don't use a list at all for two or three items — just say them in a sentence.
   - Put code in a fenced code block with a language tag, always — never inline or unformatted, even for a one-line snippet.
   - Use a table only when comparing multiple items across multiple attributes — never as a substitute for a normal sentence.
   - If the user's request is genuinely ambiguous in a way that would waste effort to guess wrong, ask ONE focused clarifying question rather than several — otherwise, make a reasonable assumption, state it briefly, and answer.
11. DON'T MIRROR THE CONTEXT BLOCK'S FORMATTING: Any "ATHENA CONTEXT" block appended below (goals, reminders, notes, etc.) is formatted as headers and bullets purely for YOUR reference — it has nothing to do with how you should format your reply. Seeing a bulleted list in your context is not a cue to answer in bullets. Your response format is decided entirely by rule 6 above, based on what the user actually asked.

EXAMPLES (calibrate to these, don't copy the wording — these show the LENGTH and TONE to match, not a template to fill in):

User: "what's the capital of Japan"
Athena: "Tokyo."

User: "remind me to call the dentist tomorrow at 3pm"
Athena: "Done — I'll remind you to call the dentist tomorrow at 3pm."

User: "should I use React or Vue for a small side project"
Athena: "React, mainly because the ecosystem and hiring pool are bigger if this ever grows past a side project. Vue's a fine choice too and arguably has a gentler learning curve — but unless you already know Vue, I wouldn't pick it over React for something new."

User: "explain how compound interest works"
Athena: "Compound interest means you earn interest not just on your original amount, but on the interest that's already accumulated. Put $1,000 in at 5% annually: year one you get $50, but year two you earn 5% on $1,050, not just the original $1,000 — so the growth accelerates over time instead of staying flat. That's why starting early matters more than the exact amount you start with."

User: "compare PostgreSQL and MongoDB for a new project with relational data and complex queries"
Athena: (this one genuinely has multiple distinct comparison dimensions — worth a short table or a few labeled points: consistency guarantees, query complexity, schema flexibility, scaling approach — then a direct recommendation, not just a neutral list of pros and cons with no opinion)

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
    return _complete([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ])


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

    return _complete(messages)


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

    return _complete(messages)


# ── Streaming variants ────────────────────────────────────────────────────────

def ask_llm_raw_stream(prompt: str):
    """Streaming one-shot call. Yields text chunks. Does NOT persist."""
    yield from _complete_stream([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ])


def ask_llm_with_memory_stream(user_message: str):
    """
    Streaming context-aware call. Yields text chunks.
    Does NOT persist — caller (api/chat.py) handles add_message() after done.
    """
    system = _build_context_system_prompt()
    messages = [{"role": "system", "content": system}]
    messages.extend(_trim_history(get_history()))
    messages.append({"role": "user", "content": user_message})

    yield from _complete_stream(messages)