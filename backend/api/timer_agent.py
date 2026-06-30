"""
backend/agents/timer_agent.py  —  Phase 18

Handles "set a timer for X minutes", "start a 5 minute timer for pasta",
"how much time is left", "cancel my timer". Distinct from ReminderAgent,
which handles scheduled-datetime reminders, not countdown timers.
"""
from __future__ import annotations

import re
from typing import Generator

from backend.agents.base import BaseAgent, AgentResult
from backend.core.llm import ask_llm_raw
from backend.core.logger import agent_logger
from backend.database.db import SessionLocal
from backend.database.models import Timer
from backend.core.request_context import get_current_user_id
from datetime import datetime, timedelta

_TIMER_KEYWORDS = {
    "timer", "countdown", "set a timer", "start a timer",
    "minute timer", "second timer", "hour timer",
    "how much time is left", "time remaining", "cancel my timer",
    "pause the timer", "pause my timer", "resume the timer",
}


class TimerAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "timer"

    @property
    def description(self) -> str:
        return (
            "Countdown timer agent. Use for 'set a timer for X minutes', "
            "'start a 10 minute timer', checking time remaining, or "
            "cancelling/pausing/resuming a running timer. NOT for "
            "scheduled reminders at a specific date/time — that's the "
            "reminder agent."
        )

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in _TIMER_KEYWORDS)

    def _detect_intent(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ("cancel", "stop", "remove", "delete")):
            return "cancel"
        if "pause" in q:
            return "pause"
        if "resume" in q or "continue" in q:
            return "resume"
        if any(w in q for w in ("how much", "time left", "time remaining", "check")):
            return "check"
        return "start"

    def _parse_duration(self, query: str) -> tuple[int | None, str | None]:
        """Returns (seconds, label) parsed from natural language."""
        q = query.lower()

        total_seconds = 0
        found_any = False

        hour_match = re.search(r"(\d+)\s*(?:hour|hr)s?", q)
        if hour_match:
            total_seconds += int(hour_match.group(1)) * 3600
            found_any = True

        min_match = re.search(r"(\d+)\s*(?:minute|min)s?", q)
        if min_match:
            total_seconds += int(min_match.group(1)) * 60
            found_any = True

        sec_match = re.search(r"(\d+)\s*(?:second|sec)s?", q)
        if sec_match:
            total_seconds += int(sec_match.group(1))
            found_any = True

        if not found_any:
            return None, None

        # Try to extract a label: "timer for pasta" / "timer called laundry"
        label = None
        label_match = re.search(r"(?:for|called|named)\s+([a-zA-Z][a-zA-Z\s]{1,30})$", q)
        if label_match:
            candidate = label_match.group(1).strip()
            # Avoid capturing duration words as labels
            if not re.search(r"\d|minute|second|hour", candidate):
                label = candidate

        return total_seconds, label

    def _get_active_timers(self, uid: int) -> list[Timer]:
        db = SessionLocal()
        try:
            return (
                db.query(Timer)
                .filter(Timer.user_id == uid, Timer.status.in_(["running", "paused"]))
                .order_by(Timer.created_at.desc())
                .all()
            )
        finally:
            db.close()

    def run(self, query: str, context: dict | None = None) -> AgentResult:
        steps = []
        agent_logger.info(f"[TimerAgent] query={query!r}")
        uid = get_current_user_id()

        intent = self._detect_intent(query)
        steps.append(f"Intent: {intent}")

        if intent == "start":
            seconds, label = self._parse_duration(query)
            if not seconds:
                return AgentResult(
                    answer="How long should I set the timer for? (e.g. '10 minutes', '1 hour 30 minutes')",
                    agent_name=self.name, steps=steps, confidence=60,
                )

            db = SessionLocal()
            try:
                timer = Timer(
                    user_id=uid,
                    label=label,
                    duration_seconds=seconds,
                    ends_at=datetime.utcnow() + timedelta(seconds=seconds),
                    status="running",
                )
                db.add(timer)
                db.commit()
                db.refresh(timer)
                timer_id = timer.id
            finally:
                db.close()

            human_duration = self._humanize(seconds)
            label_text = f' for "{label}"' if label else ""
            answer = f"⏱️ Timer set{label_text}: {human_duration}. I'll let you know when it's up."
            return AgentResult(
                answer=answer, agent_name=self.name, steps=steps, confidence=92,
                metadata={"timer_id": timer_id, "duration_seconds": seconds},
            )

        active = self._get_active_timers(uid)

        if intent == "check":
            if not active:
                return AgentResult(answer="You don't have any active timers.", agent_name=self.name, steps=steps, confidence=85)
            lines = []
            for t in active:
                if t.status == "running":
                    remaining = max(0, int((t.ends_at - datetime.utcnow()).total_seconds()))
                else:
                    remaining = t.remaining_seconds_at_pause or 0
                label_text = f' ("{t.label}")' if t.label else ""
                lines.append(f"• {self._humanize(remaining)} left{label_text} [{t.status}]")
            return AgentResult(answer="Active timers:\n" + "\n".join(lines), agent_name=self.name, steps=steps, confidence=90)

        if not active:
            return AgentResult(answer="You don't have any active timers to " + intent + ".", agent_name=self.name, steps=steps, confidence=80)

        target = active[0]  # most recent
        db = SessionLocal()
        try:
            t = db.query(Timer).filter(Timer.id == target.id).first()
            if intent == "cancel":
                t.status = "cancelled"
                answer = "✓ Timer cancelled."
            elif intent == "pause":
                if t.status != "running":
                    answer = "That timer isn't running."
                else:
                    remaining = max(0, int((t.ends_at - datetime.utcnow()).total_seconds()))
                    t.remaining_seconds_at_pause = remaining
                    t.status = "paused"
                    answer = f"⏸️ Timer paused with {self._humanize(remaining)} remaining."
            elif intent == "resume":
                if t.status != "paused":
                    answer = "That timer isn't paused."
                else:
                    remaining = t.remaining_seconds_at_pause or 0
                    t.ends_at = datetime.utcnow() + timedelta(seconds=remaining)
                    t.remaining_seconds_at_pause = None
                    t.status = "running"
                    answer = f"▶️ Timer resumed: {self._humanize(remaining)} left."
            else:
                answer = "I'm not sure what you want me to do with the timer."
            db.commit()
        finally:
            db.close()

        return AgentResult(answer=answer, agent_name=self.name, steps=steps, confidence=88)

    def _humanize(self, seconds: int) -> str:
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        parts = []
        if h: parts.append(f"{h} hour{'s' if h != 1 else ''}")
        if m: parts.append(f"{m} minute{'s' if m != 1 else ''}")
        if s and not h: parts.append(f"{s} second{'s' if s != 1 else ''}")
        return " ".join(parts) if parts else "0 seconds"

    def run_stream(self, query: str, context: dict | None = None) -> Generator[str, None, None]:
        result = self.run(query, context)
        words = result.answer.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
