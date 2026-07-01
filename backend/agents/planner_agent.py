"""
agents/planner_agent.py  —  Phase 15 fix v2

Two fixes over v1:
1. "lets start with phase 1" / "i would like to start with the basics"
   now routes to TEACH mode (delivers content) rather than PLAN mode
   (generates yet another plan structure). The LLM was always generating
   a new plan because the prompt always said "Create a detailed plan".

2. _detect_mode() distinguishes:
   - TEACH: user wants to learn/start/begin something ("lets start", "basics",
     "tell me about phase 1", "explain", "what is")
   - PLAN:  user wants a roadmap/schedule ("plan", "roadmap", "how should I",
     "create a plan", "schedule")
   - CONTINUE: user is mid-task and asking next steps ("next", "continue",
     "what's next", "move to phase 2")
"""

from __future__ import annotations

from typing import Generator

from backend.agents.base import BaseAgent, AgentResult
from backend.core.llm import ask_llm_raw, ask_llm_raw_stream
from backend.core.logger import agent_logger
from backend.tools.reminders import ReminderTool

_reminder_tool = ReminderTool()

_PLAN_KEYWORDS = {
    "plan", "planning", "schedule", "roadmap", "guide", "strategy",
    "project", "milestone", "timeline", "organise", "organize",
    "workflow", "checklist", "todo", "create a plan", "make a plan",
    "start with", "begin with", "phase", "let's start", "lets start",
    "basics", "fundamentals", "introduction to", "walk me through",
}
# Phase 24 fix ("every answer comes back long"): this used to also
# include "help me", "explain", "what is", "how does", "tell me about",
# "teach me", "show me", and "how to" -- all far too generic. "help me"
# alone matches an enormous fraction of ordinary requests ("help me
# troubleshoot this", "help me understand X"), and every one of them got
# routed through this agent's rigid 5-section plan template or the
# teach-mode template with its own forced structure, instead of just
# being answered directly. Left only phrases that specifically signal
# someone wants an actual roadmap/schedule or to start a defined
# multi-step learning path -- not just any question with a common verb.


class PlannerAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "planner"

    @property
    def description(self) -> str:
        return (
            "Planning and teaching agent. Use when the user wants a structured "
            "plan, roadmap, step-by-step guide, OR wants to learn/start a specific "
            "phase or topic from a plan already discussed."
        )

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in _PLAN_KEYWORDS)

    # ── Mode detection ────────────────────────────────────────────────────────

    def _detect_mode(self, query: str) -> str:
        """
        Returns: 'plan' | 'teach' | 'continue'

        - plan: user wants a new roadmap/plan structure
        - teach: user wants to learn content / start a phase
        - continue: user wants next steps in an existing plan
        """
        q = query.lower().strip()

        # Continue signals
        if any(w in q for w in (
            "next", "continue", "move on", "move to", "what's next",
            "next phase", "next step", "proceed",
        )):
            return "continue"

        # Teach signals — user wants content delivered, not a new plan
        if any(w in q for w in (
            "start with", "lets start", "let's start", "begin with",
            "i would like to start", "i want to start",
            "basics", "fundamentals", "introduction",
            "explain", "teach me", "tell me about",
            "what is", "what are", "how does", "walk me through",
            "show me", "give me an overview",
            "phase 1", "phase 2", "phase 3", "phase 4",
        )):
            return "teach"

        # Plan signals — user wants a new plan/roadmap
        if any(w in q for w in (
            "plan", "roadmap", "schedule", "strategy", "how to",
            "help me", "create a plan", "make a plan", "outline",
            "organize", "organise",
        )):
            return "plan"

        # Default: if short query (< 6 words) with prior context → teach
        if len(q.split()) < 6:
            return "teach"

        return "plan"

    # ── Prompts ───────────────────────────────────────────────────────────────

    def _plan_prompt(self, query: str) -> str:
        return (
            f"You are Athena, an expert planning assistant.\n\n"
            f"CRITICAL: Read the conversation history above. If this request "
            f"continues a prior topic, plan specifically about THAT topic — "
            f"do NOT generate a generic plan.\n\n"
            f"User request: {query}\n\n"
            f"Give them a plan that matches the actual scope of what they asked "
            f"for. A small, single-session task (\"plan my grocery run\", \"help me "
            f"schedule tomorrow morning\") needs a short, direct list of steps — "
            f"not overview/phases/milestones/success-criteria sections, that would "
            f"be absurd overkill for something this size. Reserve the fuller "
            f"structure (overview, phases, milestones, success criteria) for "
            f"requests that are genuinely large or multi-week, where that "
            f"structure actually helps. Be specific either way — reference the "
            f"exact subject matter from prior context rather than generic advice."
        )

    def _teach_prompt(self, query: str) -> str:
        return (
            f"You are Athena, an expert teacher and personal assistant.\n\n"
            f"CRITICAL: Read the conversation history above. The user wants to "
            f"START LEARNING or dive into a specific phase/topic from that "
            f"conversation. DO NOT generate a new plan structure — instead, "
            f"DELIVER THE ACTUAL CONTENT for what they're asking about.\n\n"
            f"User request: {query}\n\n"
            f"Identify the specific topic/phase from the conversation above and "
            f"deliver the actual content — explanations, concepts, examples — at "
            f"whatever length the topic genuinely needs. A quick clarifying "
            f"question deserves a few sentences; a real concept deserves proper "
            f"explanation. Only end with something like 'Ready for the next "
            f"concept?' if this is clearly part of an ongoing structured lesson "
            f"sequence — for a one-off question, just answer it and stop."
        )

    def _continue_prompt(self, query: str) -> str:
        return (
            f"You are Athena, a personal assistant helping with ongoing work.\n\n"
            f"The user wants to continue from where they left off. "
            f"Review the conversation history above and identify:\n"
            f"- What they were working on\n"
            f"- What was completed\n"
            f"- What the logical next step is\n\n"
            f"User request: {query}\n\n"
            f"Deliver the next step's content directly. Don't re-explain what was done."
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_milestones(self, plan_text: str, goal: str) -> list[str]:
        prompt = (
            f"From this plan, extract exactly 3 key milestones as a pipe-separated list.\n"
            f"Format each as: TASK|TIMEFRAME\n"
            f"Example: Review Phase 1 progress|Week 1\n\n"
            f"Goal: {goal}\n\nPlan:\n{plan_text[:1500]}\n\n"
            f"Return ONLY the 3 milestones, one per line, nothing else."
        )
        raw = ask_llm_raw(prompt)
        milestones = []
        for line in raw.strip().splitlines():
            line = line.strip()
            if "|" in line and line:
                milestones.append(line)
        return milestones[:3]

    def _save_reminders(self, milestones: list[str]) -> list[str]:
        saved = []
        for milestone in milestones:
            try:
                result = _reminder_tool.run(f"save:{milestone}")
                if "successfully" in result.lower():
                    task, timeframe = milestone.split("|", 1)
                    saved.append(f"✓ Reminder set: {task.strip()} ({timeframe.strip()})")
            except Exception:
                pass
        return saved

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, query: str, context: dict | None = None) -> AgentResult:
        steps = []
        agent_logger.info(f"[PlannerAgent] query={query!r}")
        ctx = context or {}

        mode = self._detect_mode(query)
        steps.append(f"Mode: {mode}")

        if mode == "teach":
            steps.append("Delivering content for requested topic…")
            prompt = self.build_context_aware_prompt(query, self._teach_prompt(query))
            answer = ask_llm_raw(prompt)
            return AgentResult(
                answer=answer,
                agent_name=self.name,
                sources=[],
                steps=steps,
                confidence=88,
                metadata={"mode": "teach"},
            )

        if mode == "continue":
            steps.append("Identifying next steps from prior context…")
            prompt = self.build_context_aware_prompt(query, self._continue_prompt(query))
            answer = ask_llm_raw(prompt)
            return AgentResult(
                answer=answer,
                agent_name=self.name,
                sources=[],
                steps=steps,
                confidence=88,
                metadata={"mode": "continue"},
            )

        # mode == "plan"
        steps.append("Generating structured plan…")
        prompt = self.build_context_aware_prompt(query, self._plan_prompt(query))
        plan_text = ask_llm_raw(prompt)

        reminders_created = []
        if ctx.get("create_reminders", True):
            steps.append("Extracting milestones…")
            milestones = self._extract_milestones(plan_text, query)
            if milestones:
                steps.append(f"Creating {len(milestones)} reminders…")
                reminders_created = self._save_reminders(milestones)

        full_answer = plan_text
        if reminders_created:
            full_answer += "\n\n---\n**Reminders Created:**\n" + "\n".join(reminders_created)

        return AgentResult(
            answer=full_answer,
            agent_name=self.name,
            sources=[],
            steps=steps,
            confidence=90,
            metadata={"mode": "plan", "reminders_created": len(reminders_created)},
        )

    def run_stream(
        self, query: str, context: dict | None = None
    ) -> Generator[str, None, None]:
        agent_logger.info(f"[PlannerAgent] stream query={query!r}")
        mode = self._detect_mode(query)

        if mode == "teach":
            prompt = self.build_context_aware_prompt(query, self._teach_prompt(query))
        elif mode == "continue":
            prompt = self.build_context_aware_prompt(query, self._continue_prompt(query))
        else:
            prompt = self.build_context_aware_prompt(query, self._plan_prompt(query))

        for chunk in ask_llm_raw_stream(prompt):
            yield chunk