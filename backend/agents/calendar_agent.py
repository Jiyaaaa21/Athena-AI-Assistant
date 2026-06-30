"""
backend/agents/calendar_agent.py  —  Phase 20

Natural-language access to the user's REAL Google Calendar — "what's on
my calendar today", "do I have anything tomorrow", "schedule a meeting
with John at 3pm Friday". This is the agent that turns the OAuth
integration into something the user can actually talk to.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Generator

from backend.agents.base import BaseAgent, AgentResult
from backend.core.llm import ask_llm_raw
from backend.core.logger import agent_logger
from backend.core.request_context import get_current_user_id
from backend.integrations import google_calendar as gcal

_CALENDAR_KEYWORDS = {
    "calendar", "my schedule", "schedule a meeting", "schedule an event",
    "what's on my calendar", "whats on my calendar", "do i have anything",
    "any meetings", "any events", "book a meeting", "add to my calendar",
    "add an event", "create an event", "cancel my meeting", "free time",
    "am i free", "what do i have today", "what do i have tomorrow",
}


class CalendarAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "calendar"

    @property
    def description(self) -> str:
        return (
            "Real Google Calendar agent — reads and creates ACTUAL calendar "
            "events (not internal reminders). Use for 'what's on my calendar', "
            "'am I free at 3pm', 'schedule a meeting', or checking/booking "
            "real appointments."
        )

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in _CALENDAR_KEYWORDS)

    def _not_connected_response(self) -> AgentResult:
        return AgentResult(
            answer=(
                "Your Google Calendar isn't connected yet. Go to "
                "**Settings → Calendar** and click 'Connect Google Calendar' "
                "to let me see and manage your real schedule."
            ),
            agent_name=self.name, steps=["Calendar not connected"], confidence=95,
        )

    def _detect_intent(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ("schedule", "book", "add an event", "add to my calendar", "create an event")):
            return "create"
        if any(w in q for w in ("cancel", "delete", "remove")):
            return "delete"
        return "read"

    def _parse_date_range(self, query: str) -> tuple[datetime, datetime, str]:
        """Returns (start, end, human_label) for the requested window."""
        q = query.lower()
        now = datetime.now(timezone.utc)

        if "tomorrow" in q:
            start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=1), "tomorrow"
        if "this week" in q or "week" in q:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=7), "this week"
        if "today" in q or "anything" in q or not any(w in q for w in ("tomorrow", "week")):
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=1), "today"
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1), "today"

    def run(self, query: str, context: dict | None = None) -> AgentResult:
        steps = []
        agent_logger.info(f"[CalendarAgent] query={query!r}")
        uid = get_current_user_id()

        if not uid or not gcal.is_connected(uid):
            return self._not_connected_response()

        intent = self._detect_intent(query)
        steps.append(f"Intent: {intent}")

        if intent == "read":
            start, end, label = self._parse_date_range(query)
            steps.append(f"Fetching events for {label}")
            try:
                events = gcal.list_events(uid, start, end)
            except Exception as e:
                return AgentResult(answer=f"I couldn't reach your calendar: {e}", agent_name=self.name, steps=steps, confidence=40)

            if not events:
                return AgentResult(answer=f"You have nothing on your calendar {label}. Clear schedule!", agent_name=self.name, steps=steps, confidence=92)

            lines = []
            for e in events:
                if e["allDay"]:
                    time_str = "All day"
                else:
                    try:
                        from dateutil import parser as dp
                        dt = dp.isoparse(e["start"])
                        time_str = dt.strftime("%I:%M %p").lstrip("0")
                    except Exception:
                        time_str = ""
                loc = f" @ {e['location']}" if e.get("location") else ""
                lines.append(f"• **{time_str}** — {e['title']}{loc}")

            answer = f"You have {len(events)} event(s) {label}:\n\n" + "\n".join(lines)
            return AgentResult(answer=answer, agent_name=self.name, steps=steps, confidence=92, metadata={"event_count": len(events)})

        if intent == "create":
            steps.append("Parsing event details with LLM")
            now_str = datetime.now(timezone.utc).strftime("%A, %d %B %Y, %H:%M UTC")
            prompt = (
                f"Current UTC time: {now_str}\n\n"
                f"Extract a calendar event from this request. Return EXACTLY these lines:\n"
                f"TITLE: <event title>\n"
                f"START: <ISO 8601 datetime in UTC, e.g. 2026-07-01T15:00:00Z>\n"
                f"END: <ISO 8601 datetime in UTC, default to 1 hour after start if not specified>\n"
                f"LOCATION: <location, or NONE>\n\n"
                f"Request: {query}"
            )
            raw = ask_llm_raw(prompt)
            parsed = {}
            for line in raw.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    parsed[k.strip().upper()] = v.strip()

            title = parsed.get("TITLE")
            start_str = parsed.get("START")
            end_str = parsed.get("END")
            location = parsed.get("LOCATION")
            if location == "NONE":
                location = None

            if not title or not start_str:
                return AgentResult(
                    answer="I couldn't figure out the event details. Could you tell me the title and when it should be?",
                    agent_name=self.name, steps=steps, confidence=55,
                )

            try:
                from dateutil import parser as dp
                start_dt = dp.isoparse(start_str)
                end_dt = dp.isoparse(end_str) if end_str else start_dt + timedelta(hours=1)
                event = gcal.create_event(uid, title, start_dt, end_dt, location=location)
            except Exception as e:
                return AgentResult(answer=f"I couldn't create that event: {e}", agent_name=self.name, steps=steps, confidence=40)

            local_time = start_dt.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")
            return AgentResult(
                answer=f"✓ Added to your calendar: **{title}** — {local_time}",
                agent_name=self.name, steps=steps, confidence=90,
                metadata={"event_id": event.get("id")},
            )

        # delete intent — needs the user to specify which event; keep it simple
        return AgentResult(
            answer="Which event would you like me to cancel? Tell me the title or check your calendar first.",
            agent_name=self.name, steps=steps, confidence=60,
        )

    def run_stream(self, query: str, context: dict | None = None) -> Generator[str, None, None]:
        result = self.run(query, context)
        words = result.answer.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
