"""
agents/orchestrator.py  —  Phase 13 + Phase 15 PENDING-STATE fix

ROOT CAUSE of "study chemistry" → Research agent instead of Reminder agent:

When an agent asks a clarifying question ("What time would you like to change
it to?"), the conversation is mid-task. The user's answer ("study chemistry",
"1pm", "tomorrow") is a REPLY to that question — not a new request. But the
orchestrator treated every message identically, routing "study chemistry"
through the full pipeline which sent it to Research.

FIX — Pending-state detection (Layer -1):
  Inspect the last Athena message. If it ended with a clarifying question
  from a specific agent (incomplete=True in metadata, or question pattern),
  lock the next turn to that same agent — skip all other routing.

This is how real assistants work: they maintain conversational state.
"""

from __future__ import annotations

import re
from typing import Generator

from backend.agents.base import BaseAgent, AgentResult
from backend.agents.research_agent import ResearchAgent
from backend.agents.planner_agent import PlannerAgent
from backend.agents.note_agent import NoteAgent
from backend.agents.reminder_agent import ReminderAgent
from backend.agents.timer_agent import TimerAgent
from backend.agents.calendar_agent import CalendarAgent
from backend.agents.rag_agent import RAGAgent
from backend.agents.web_search_agent import WebSearchAgent
from backend.agents.email_agent import EmailAgent
from backend.agents.action_agent import ActionAgent
from backend.core.llm import (
    ask_llm_raw, ask_llm_with_memory, ask_llm_with_memory_stream,
)
from backend.core.memory_service import get_history, add_message
from backend.core.logger import agent_logger

# ── Registry ──────────────────────────────────────────────────────────────────

ALL_AGENTS: list[BaseAgent] = [
    ResearchAgent(),
    PlannerAgent(),
    NoteAgent(),
    ReminderAgent(),
    TimerAgent(),
    CalendarAgent(),
    RAGAgent(),
    WebSearchAgent(),
    EmailAgent(),
    ActionAgent(),
]

AGENT_MAP: dict[str, BaseAgent] = {a.name: a for a in ALL_AGENTS}

# ── Clarifying-question patterns ──────────────────────────────────────────────
# If the last Athena reply ends with one of these, the conversation is
# mid-task and the next user message is a reply, not a new request.

_PENDING_QUESTION_PATTERNS = [
    r"what time would you like",
    r"when would you like",
    r"when should i remind you",
    r"what should i remind you about",
    r"what would you like to change it to",
    r"what would you like to rename",
    r"what would you like the new",
    r"could you tell me",
    r"can you tell me",
    r"what do you mean by",
    r"which (note|reminder|goal|project) (do you mean|are you referring to)",
    r"what time should",
    r"would you like me to",
    r"\?\s*$",   # ends with a question mark (last resort)
]

_PENDING_RE = [re.compile(p, re.IGNORECASE) for p in _PENDING_QUESTION_PATTERNS]

# Maps question keywords → agent name, for fast lock-in
_QUESTION_AGENT_HINTS: dict[str, str] = {
    "remind":   "reminder",
    "reminder": "reminder",
    "note":     "note",
    "rename":   "note",
    "goal":     "planner",
    "project":  "planner",
    "time":     "reminder",
    "send this": "email",
    "should i send": "email",
    "trigger": "action",   
}


def _detect_pending_agent(last_assistant_text: str) -> str | None:
    """
    If the last Athena message was a clarifying question mid-task,
    return the agent name that should handle the follow-up.
    Returns None if the conversation is not mid-task.

    Phase 22 fix: hints are checked longest-keyword-first instead of in
    dict insertion order. Previously a short generic word like "project"
    (-> "planner") could match inside unrelated content further down the
    message -- e.g. an EmailAgent draft with the subject "Project
    update" -- and win over a more specific hint like "should i send"
    (-> "email") simply because it appeared earlier in the dict.
    Real case this fixed: a user confirmed an email draft titled
    "Project update" with "yes", and the pending-state lock incorrectly
    routed to the planner agent instead of back to email, because
    "project" was checked before "should i send" and both are substrings
    of the same draft text. Checking longest keywords first makes
    specific multi-word phrases always take priority over short
    single-word ones, regardless of dict order or draft content.
    """
    if not last_assistant_text:
        return None

    # Check if it matches a clarifying question pattern
    text_lower = last_assistant_text.lower().strip()
    is_question = any(r.search(text_lower) for r in _PENDING_RE)
    if not is_question:
        return None

    # Identify which agent was asking — longest/most specific hint wins.
    sorted_hints = sorted(
        _QUESTION_AGENT_HINTS.items(), key=lambda kv: len(kv[0]), reverse=True
    )
    for hint_kw, agent_name in sorted_hints:
        if hint_kw in text_lower:
            return agent_name

    return None   # question, but can't determine agent → fall through to normal routing


def _get_last_assistant_message() -> str:
    """Return the most recent assistant message from conversation history."""
    try:
        history = get_history()
        for msg in reversed(history):
            if msg.get("role") == "assistant":
                return msg.get("content", "")
    except Exception:
        pass
    return ""


# ── Conversational shortcut patterns ─────────────────────────────────────────

_CONVERSATIONAL_PATTERNS = [
    r"^(hi|hello|hey|sup|yo|howdy)[.!?]?$",
    r"^how are you(\?)?$",
    r"^what('s| is) your name(\?)?$",
    r"^who are you(\?)?$",
    r"^(thanks|thank you|thx|ty)[.!?]?$",
    r"^(ok|okay|cool|great|nice|sounds good)[.!?]?$",
    r"^(yes|no|yep|nope|sure|alright)[.!?]?$",
    r"^tell me (a )?joke(\?)?$",
    r"^what (can you do|are you capable of)(\?)?$",
]
_CONV_RE = [re.compile(p, re.IGNORECASE) for p in _CONVERSATIONAL_PATTERNS]


def _is_conversational(query: str) -> bool:
    q = query.strip()
    if len(q.split()) > 6:
        return False
    return any(r.match(q) for r in _CONV_RE)


# ── Multi-agent trigger ───────────────────────────────────────────────────────

_MULTI_AGENT_KEYWORDS = {
    "and also", "as well as", "additionally",
    "research and plan", "plan and remind", "find and save",
    "summarize and", "search and note",
}


def _needs_multi_agent(query: str) -> bool:
    q = query.lower()
    hits = sum(1 for a in ALL_AGENTS if a.can_handle(q))
    return hits >= 2 or any(kw in q for kw in _MULTI_AGENT_KEYWORDS)


# ── Phase 23: Multi-step chain trigger ────────────────────────────────────────
# Distinct from _needs_multi_agent above: that path runs 2+ agents on the SAME
# original query independently and synthesises their answers side by side --
# fine for "research X and also note that I like Y" where the two halves don't
# depend on each other. It falls short for genuinely sequential requests where
# step 2 needs to know what step 1 produced ("find a good pizza place near me
# and remind me to order at 7pm" -- the reminder should reference the place
# step 1 actually found, not just run blind on the full original sentence).

_SEQUENTIAL_CONNECTORS = {
    " then ", " after that", " once that", " once you", " once done",
    " and then ", " next, ", " after doing ",
}
# Phase 24 fix: "first " and bare "next, " were too weak a signal on
# their own -- ordinary voice queries like "what's the first thing on my
# calendar today" or "who's up next" would match, and since _needs_chain
# firing means _build_chain_plan() runs (an extra synchronous LLM call)
# BEFORE any status/token is yielded to the stream, a false positive here
# silently added a full extra round-trip of latency to what should have
# been an instant single-agent answer. Removed "first " entirely and
# require connectors to appear as whole-word phrases with surrounding
# spaces, so they only match genuine multi-step phrasing ("first check
# my calendar, then remind me...") rather than incidental word overlap.


def _needs_chain(query: str) -> bool:
    q = f" {query.lower()} "
    hits = sum(1 for a in ALL_AGENTS if a.can_handle(query))
    has_connector = any(kw in q for kw in _SEQUENTIAL_CONNECTORS)
    return hits >= 2 and has_connector


def _build_chain_plan(query: str) -> list[dict]:
    """
    Asks the LLM to decompose a sequential multi-step request into an
    ordered plan of {agent, instruction} steps. Returns [] if the LLM's
    response can't be parsed or names an unknown agent -- callers must
    treat an empty plan as "fall back to normal multi-agent handling",
    never as "run zero steps and say nothing".
    """
    agent_descriptions = "\n".join(f'- "{a.name}": {a.description}' for a in ALL_AGENTS)
    prompt = (
        "You are Athena's task planner. The user's request has multiple, "
        "SEQUENTIAL steps -- a later step may depend on what an earlier step "
        "produces. Break it into an ordered list of steps, each assigned to "
        "exactly one specialist agent.\n\n"
        f"Available agents:\n{agent_descriptions}\n\n"
        f"User request: {query}\n\n"
        "Respond with ONLY a JSON array, nothing else, in exactly this shape:\n"
        '[{"agent": "agent_name", "instruction": "what this step should do, '
        'written as a standalone instruction"}, ...]\n\n'
        "Keep it to the minimum steps actually needed (usually 2-3). Every "
        '"agent" value must be one of the agent names listed above exactly.'
    )
    raw = ask_llm_raw(prompt).strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        import json as _json
        steps = _json.loads(raw)
    except Exception:
        agent_logger.warning(f"[Orchestrator] chain plan not valid JSON: {raw[:200]!r}")
        return []

    plan = []
    for step in steps:
        name = (step.get("agent") or "").strip()
        instruction = (step.get("instruction") or "").strip()
        if name in AGENT_MAP and instruction:
            plan.append({"agent": name, "instruction": instruction})
    return plan


def _execute_chain(plan: list[dict]) -> list[AgentResult]:
    """
    Runs each planned step in order, feeding the previous step's answer
    into the next step's instruction as extra context -- this is the
    actual "chaining" part: step 2 sees what step 1 produced instead of
    only ever seeing the original user sentence.
    """
    results: list[AgentResult] = []
    prior_context = ""
    for step in plan:
        agent = AGENT_MAP[step["agent"]]
        instruction = step["instruction"]
        if prior_context:
            instruction = (
                f"{instruction}\n\n"
                f"(Context from the previous step of this task: {prior_context})"
            )
        try:
            r = agent.run(instruction)
            results.append(r)
            prior_context = r.answer[:500]
        except Exception as e:
            agent_logger.error(f"[Orchestrator] chain step failed ({step['agent']}): {e}")
            results.append(AgentResult(
                answer=f"(This step failed: {e})",
                agent_name=step["agent"],
                steps=[f"Chain step failed: {step['instruction']}"],
            ))
    return results


def _synthesise_chain(query: str, plan: list[dict], results: list[AgentResult]) -> str:
    combined = "\n\n---\n\n".join(
        f"[STEP {i+1}: {step['agent'].upper()}] {step['instruction']}\n→ {r.answer}"
        for i, (step, r) in enumerate(zip(plan, results))
    )
    prompt = (
        f"You are Athena. You just completed a multi-step task for the user by "
        f"running each step through a specialist agent in order.\n\n"
        f"Original request: {query}\n\n"
        f"Steps completed:\n{combined}\n\n"
        f"Confirm what happened at each step in plain language, in your own words "
        f"-- don't just restate the raw agent outputs. Keep it as short as the "
        f"actual result allows; a two-step task usually needs two sentences, not "
        f"a formal report."
    )
    return ask_llm_raw(prompt)


# ── LLM Router ────────────────────────────────────────────────────────────────

def _build_router_prompt(query: str) -> str:
    agent_descriptions = "\n".join(
        f'- "{a.name}": {a.description}' for a in ALL_AGENTS
    )
    history = get_history()
    recent = history[-6:] if history else []
    history_str = ""
    if recent:
        history_str = "\n\nRecent conversation:\n" + "\n".join(
            f"{m['role'].capitalize()}: {m['content'][:200]}" for m in recent
        )

    return (
        f"You are Athena's routing system. Pick the best agent(s) for a user query.\n\n"
        f"Available agents:\n{agent_descriptions}"
        f"{history_str}\n\n"
        f"Current User Query: {query}\n\n"
        f"CRITICAL: If the user's message is a short follow-up (a city name, a yes/no, "
        f"a number, a time, a topic name, a clarification) to a prior message, route to "
        f"the SAME agent type as the previous Athena response. Never treat follow-ups as "
        f"new independent requests.\n\n"
        f"Rules:\n"
        f"1. If ONE agent is clearly best, respond: AGENT: agent_name\n"
        f"2. If TWO agents should collaborate, respond: MULTI: agent1,agent2\n"
        f"3. If no agent is needed (pure conversation/general knowledge), respond: NONE\n\n"
        f"Respond with ONLY one of the above formats, nothing else."
    )


def _llm_route(query: str) -> tuple[str, list[str]]:
    raw = ask_llm_raw(_build_router_prompt(query)).strip()
    if raw.upper().startswith("NONE"):
        return "none", []
    if raw.upper().startswith("MULTI:"):
        names_part = raw.split(":", 1)[-1].strip()
        names = [n.strip() for n in names_part.split(",") if n.strip() in AGENT_MAP]
        if names:
            return "multi", names[:3]
    if raw.upper().startswith("AGENT:"):
        name = raw.split(":", 1)[-1].strip()
        if name in AGENT_MAP:
            return "single", [name]
    matches = [a.name for a in ALL_AGENTS if a.can_handle(query)]
    if matches:
        return "single", [matches[0]]
    return "none", []


# ── Multi-agent synthesiser ───────────────────────────────────────────────────

def _synthesise_multi(query: str, results: list[AgentResult]) -> str:
    combined = "\n\n---\n\n".join(
        f"[{r.agent_name.upper()} AGENT RESPONSE]\n{r.answer}" for r in results
    )
    prompt = (
        f"You are Athena. Multiple specialist agents have contributed answers.\n\n"
        f"Original Question: {query}\n\n"
        f"Agent Responses:\n{combined}\n\n"
        f"Synthesise into ONE unified answer in your own words, without duplication. "
        f"Match the length and structure to what the combined content actually "
        f"needs -- don't add headings or sections just because there were multiple "
        f"sources; most of the time a couple of connected sentences is enough."
    )
    return ask_llm_raw(prompt)


# ── Proactive hint ────────────────────────────────────────────────────────────

def _get_proactive_hint(query: str) -> str:
    try:
        from backend.core.context_builder import build_user_context
        ctx = build_user_context()
        overdue = ctx.get("overdue_reminders", [])
        for r in overdue[:3]:
            keywords = r.lower().split()
            if any(kw in query.lower() for kw in keywords if len(kw) > 4):
                # Phase 24 fix: the emoji + italics + bold "💡 *By the way...*"
                # template was another hardcoded string bypassing the LLM's
                # tone tuning entirely -- it looked exactly like the canned
                # chatbot styling the rest of Athena was deliberately tuned
                # away from. A plain aside, appended as a normal sentence.
                return f"\n\nBy the way — you still have \"{r}\" overdue."
        return ""
    except Exception:
        return ""


def _conversational_response(query: str) -> AgentResult:
    answer = ask_llm_with_memory(query)
    hint = _get_proactive_hint(query)
    if hint:
        answer += hint
    return AgentResult(
        answer=answer,
        agent_name="athena",
        steps=["Context-aware conversational response"],
        confidence=95,
    )


# ── Core routing logic (shared by streaming + non-streaming) ──────────────────

def _resolve_agent(query: str) -> tuple[str, list[str]]:
    """
    Returns (mode, agent_names).
    Applies all routing layers including the pending-state check.

    Phase 19 fix: the old Layer 2 (LLM router) fired a full extra Groq
    call BEFORE the actual response-generating call even started,
    whenever heuristics didn't cleanly match exactly one agent. For
    voice mode this was a major latency contributor — every query that
    fell through heuristics (most general-knowledge questions, since
    they don't contain a tool keyword like "remind" or "note") paid a
    full sequential LLM round-trip just to decide "use the conversational
    fallback," which is also what it almost always concluded anyway.

    Tightened to skip the LLM router in the two cases where its answer
    is either obvious or low-stakes:
      - Zero heuristic matches → go straight to conversational fallback.
        A real assistant answering general questions directly (not
        routing them through a specialist agent) is also just correct
        behavior, not only a latency shortcut.
      - Exactly one heuristic match, even if a stray second keyword
        triggered the multi-agent flag → just use that one match rather
        than asking the LLM to confirm something already unambiguous.

    The LLM router is still consulted when 2+ DISTINCT agents genuinely
    matched — that's the one case where picking wrong is likely and an
    extra ~300-500ms is worth it for correctness.
    """
    # Layer -1: Pending-state — Athena was mid-task asking a clarifying question
    last_msg = _get_last_assistant_message()
    pending_agent = _detect_pending_agent(last_msg)
    if pending_agent:
        agent_logger.info(f"[Orchestrator] → PENDING STATE lock → {pending_agent}")
        return "single", [pending_agent]

    # Layer 0: Pure social/conversational
    if _is_conversational(query):
        return "none", []

    # Layer 1: Heuristic matching
    heuristic_matches = [a for a in ALL_AGENTS if a.can_handle(query)]

    if len(heuristic_matches) == 0:
        # No tool keyword matched at all — skip the LLM router entirely
        # and answer conversationally. Saves a full LLM round-trip on
        # the most common case (general questions with no special verb).
        agent_logger.info("[Orchestrator] → no heuristic match: conversational fallback (router skipped)")
        return "none", []

    if len(heuristic_matches) == 1:
        # Exactly one agent's keywords matched — use it directly even if
        # _needs_multi_agent() also fired on a stray second keyword. The
        # single match is almost always correct; consulting the LLM
        # router to confirm this costs latency for very little accuracy
        # gain.
        agent_logger.info(f"[Orchestrator] → heuristic (single match): {heuristic_matches[0].name}")
        return "single", [heuristic_matches[0].name]

    # Layer 1.5 (Phase 23): 2+ agents matched AND the phrasing has a
    # sequential connector ("...then...", "first...then...") — this is a
    # dependent multi-step task, not independent parallel sub-questions.
    # Handled by the chain planner instead of the plain multi-agent path
    # below, since the plain path runs every agent on the same original
    # query and can't pass step 1's result into step 2.
    if _needs_chain(query):
        agent_logger.info("[Orchestrator] → sequential connector detected: attempting chain plan")
        return "chain", []

    # 2+ distinct agents matched — genuinely ambiguous, worth the LLM
    # router's extra latency to pick correctly (or decide on multi-agent
    # collaboration).
    mode, names = _llm_route(query)
    agent_logger.info(f"[Orchestrator] → LLM route (multi-match): {mode} {names}")
    return mode, names


# ── Public API ────────────────────────────────────────────────────────────────

def route_and_run(query: str, conv_id: int | None = None) -> AgentResult:
    agent_logger.info(f"[Orchestrator] query={query!r}")

    # Phase 18: routine trigger phrases take priority over normal agent
    # routing — if the user's message matches a saved routine's trigger
    # phrase ("good morning"), run every step in sequence instead of
    # treating it as a single ordinary query.
    try:
        from backend.core.request_context import get_current_user_id
        from backend.api.routines import find_matching_routine
        uid = get_current_user_id()
        if uid:
            matched_routine = find_matching_routine(query, uid)
            if matched_routine:
                agent_logger.info(f"[Orchestrator] Routine matched: {matched_routine.name}")
                import json as _json
                results = []
                for step_query in _json.loads(matched_routine.steps):
                    try:
                        step_mode, step_names = _resolve_agent(step_query)
                        if step_mode == "single" and step_names:
                            r = AGENT_MAP[step_names[0]].run(step_query)
                        else:
                            r = _conversational_response(step_query)
                        results.append(f"**{step_query}**\n{r.answer}")
                    except Exception as e:
                        results.append(f"**{step_query}**\n(This step failed: {e})")
                combined = f"Running your \"{matched_routine.name}\" routine:\n\n" + "\n\n---\n\n".join(results)
                return AgentResult(
                    answer=combined, agent_name="routine",
                    steps=[f"Routine: {matched_routine.name}"],
                    metadata={"routine_id": matched_routine.id},
                )
    except Exception as e:
        agent_logger.warning(f"[Orchestrator] Routine matching failed (non-fatal): {e}")

    mode, selected_names = _resolve_agent(query)

    if mode == "chain":
        plan = _build_chain_plan(query)
        if not plan:
            # Planner couldn't produce a usable step list -- fall back to
            # the ordinary multi-agent path (run heuristic matches on the
            # original query, synthesise) rather than silently doing
            # nothing.
            agent_logger.info("[Orchestrator] chain plan empty, falling back to multi-agent")
            mode, selected_names = _llm_route(query)
        else:
            agent_logger.info(f"[Orchestrator] chain plan: {[s['agent'] for s in plan]}")
            results = _execute_chain(plan)
            if not results:
                return _conversational_response(query)
            synthesised = _synthesise_chain(query, plan, results)
            return AgentResult(
                answer=synthesised,
                agent_name="chain:" + "+".join(r.agent_name for r in results),
                sources=[s for r in results for s in r.sources],
                steps=[f"Step {i+1} [{plan[i]['agent']}]: {plan[i]['instruction']}" for i in range(len(plan))],
                metadata={"agents_used": [r.agent_name for r in results], "chain": True},
            )

    if mode == "none" or not selected_names:
        return _conversational_response(query)

    if mode == "single":
        return AGENT_MAP[selected_names[0]].run(query)

    # Multi
    results = []
    for name in selected_names:
        try:
            results.append(AGENT_MAP[name].run(query))
        except Exception as e:
            agent_logger.error(f"[Orchestrator] Agent {name} failed: {e}")

    if not results:
        return _conversational_response(query)
    if len(results) == 1:
        return results[0]

    synthesised = _synthesise_multi(query, results)
    return AgentResult(
        answer=synthesised,
        agent_name="multi:" + "+".join(r.agent_name for r in results),
        sources=[s for r in results for s in r.sources],
        steps=[f"[{r.agent_name}] {st}" for r in results for st in r.steps],
        metadata={"agents_used": [r.agent_name for r in results]},
    )


def route_and_stream(
    query: str,
    conv_id: int | None = None,
) -> Generator[dict, None, AgentResult]:
    agent_logger.info(f"[Orchestrator] stream query={query!r}")

    # Phase 18: routine trigger phrases take priority, same as route_and_run.
    # Streamed word-by-word for a consistent voice/chat experience.
    try:
        from backend.core.request_context import get_current_user_id
        from backend.api.routines import find_matching_routine
        uid = get_current_user_id()
        if uid:
            matched_routine = find_matching_routine(query, uid)
            if matched_routine:
                agent_logger.info(f"[Orchestrator] Routine matched (stream): {matched_routine.name}")
                yield {"type": "status", "text": f"Running \"{matched_routine.name}\" routine…", "agent": "routine"}
                import json as _json
                results = []
                for step_query in _json.loads(matched_routine.steps):
                    try:
                        step_mode, step_names = _resolve_agent(step_query)
                        if step_mode == "single" and step_names:
                            r = AGENT_MAP[step_names[0]].run(step_query)
                        else:
                            r = _conversational_response(step_query)
                        results.append(f"**{step_query}**\n{r.answer}")
                    except Exception as e:
                        results.append(f"**{step_query}**\n(This step failed: {e})")
                combined = f"Running your \"{matched_routine.name}\" routine:\n\n" + "\n\n---\n\n".join(results)
                words = combined.split(" ")
                for i, word in enumerate(words):
                    yield {"type": "token", "text": word + (" " if i < len(words) - 1 else "")}
                result = AgentResult(
                    answer=combined, agent_name="routine",
                    steps=[f"Routine: {matched_routine.name}"],
                    metadata={"routine_id": matched_routine.id},
                )
                yield {"type": "done", "result": result}
                return result
    except Exception as e:
        agent_logger.warning(f"[Orchestrator] Routine matching failed in stream (non-fatal): {e}")

    mode, selected_names = _resolve_agent(query)

    if mode == "chain":
        plan = _build_chain_plan(query)
        if not plan:
            agent_logger.info("[Orchestrator] chain plan empty (stream), falling back to multi-agent")
            mode, selected_names = _llm_route(query)
        else:
            agent_logger.info(f"[Orchestrator] chain plan (stream): {[s['agent'] for s in plan]}")
            for i, step in enumerate(plan):
                yield {"type": "status", "text": f"Step {i+1}/{len(plan)}: {step['agent']} agent…", "agent": step["agent"]}
            results = _execute_chain(plan)
            if not results:
                yield {"type": "status", "text": "Athena is thinking…", "agent": None}
                full = ""
                for chunk in ask_llm_with_memory_stream(query):
                    full += chunk
                    yield {"type": "token", "text": chunk}
                result = AgentResult(answer=full, agent_name="athena", steps=["Conversational response"])
                yield {"type": "done", "result": result}
                return result

            yield {"type": "status", "text": "Summarising the completed steps…", "agent": None}
            synthesised = _synthesise_chain(query, plan, results)
            words = synthesised.split(" ")
            for i, word in enumerate(words):
                yield {"type": "token", "text": word + (" " if i < len(words) - 1 else "")}
            result = AgentResult(
                answer=synthesised,
                agent_name="chain:" + "+".join(r.agent_name for r in results),
                sources=[s for r in results for s in r.sources],
                steps=[f"Step {i+1} [{plan[i]['agent']}]: {plan[i]['instruction']}" for i in range(len(plan))],
                metadata={"agents_used": [r.agent_name for r in results], "chain": True},
            )
            yield {"type": "done", "result": result}
            return result

    if mode == "none" or not selected_names:
        yield {"type": "status", "text": "Athena is thinking…", "agent": None}
        full = ""
        for chunk in ask_llm_with_memory_stream(query):
            full += chunk
            yield {"type": "token", "text": chunk}
        result = AgentResult(answer=full, agent_name="athena", steps=["Conversational response"])
        yield {"type": "done", "result": result}
        return result

    if mode == "single":
        agent = AGENT_MAP[selected_names[0]]
        yield {"type": "status", "text": f"Activating {agent.name} agent…", "agent": agent.name}

        sources = []
        if agent.name == "rag":
            yield {"type": "status", "text": "Searching documents…", "agent": agent.name}
            try:
                from backend.rag.rag_pipeline import rag_answer
                sources = rag_answer(query).get("sources", [])
            except Exception:
                pass

        yield {"type": "status", "text": "Generating response…", "agent": agent.name}
        full = ""
        for chunk in agent.run_stream(query):
            full += chunk
            yield {"type": "token", "text": chunk}

        result = AgentResult(
            answer=full,
            agent_name=agent.name,
            sources=sources,
            steps=[f"Routed to {agent.name} agent"],
        )
        yield {"type": "done", "result": result}
        return result

    # Multi-agent
    all_results: list[AgentResult] = []
    for name in selected_names:
        yield {"type": "status", "text": f"Running {name} agent…", "agent": name}
        try:
            all_results.append(AGENT_MAP[name].run(query))
        except Exception as e:
            agent_logger.error(f"[Orchestrator] {name} failed: {e}")

    if not all_results:
        yield {"type": "status", "text": "Generating response…", "agent": None}
        full = ""
        for chunk in ask_llm_with_memory_stream(query):
            full += chunk
            yield {"type": "token", "text": chunk}
        result = AgentResult(answer=full, agent_name="athena", steps=[])
        yield {"type": "done", "result": result}
        return result

    yield {"type": "status", "text": "Synthesising response…", "agent": None}
    synthesised = _synthesise_multi(query, all_results)
    for i, word in enumerate(synthesised.split(" ")):
        yield {"type": "token", "text": word + (" " if i < len(synthesised.split(" ")) - 1 else "")}

    result = AgentResult(
        answer=synthesised,
        agent_name="multi:" + "+".join(r.agent_name for r in all_results),
        sources=[s for r in all_results for s in r.sources],
        steps=[f"[{r.agent_name}] {st}" for r in all_results for st in r.steps],
        metadata={"agents_used": [r.agent_name for r in all_results]},
    )
    yield {"type": "done", "result": result}
    return result