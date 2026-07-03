"""
agents/reminder_agent.py  —  Phase 15 complete fix v2
"""

from __future__ import annotations

from typing import Generator
from datetime import datetime
import json

from backend.agents.base import BaseAgent, AgentResult
from backend.core.llm import ask_llm_raw
from backend.core.logger import agent_logger
from backend.tools.reminders import ReminderTool
from backend.database.db import SessionLocal
from backend.database.models import Reminder, UserPreference
from backend.core.request_context import get_current_user_id

_reminder_tool = ReminderTool()

_REMINDER_KEYWORDS = {
    "remind", "reminder", "reminders", "don't forget", "don't let me forget",
    "schedule", "due", "deadline", "alarm", "alert", "notify",
    "my reminders", "show reminders", "list reminders", "what reminders",
    "upcoming", "pending tasks",
    "change the time", "change the timing", "reschedule",
    "move the reminder", "update the reminder",
    "change reminder", "change the reminder", "postpone", "push back",
    "delete reminder", "remove reminder", "cancel reminder",
    "existing reminder", "the reminder", "that reminder",
    "i would like to change", "i want to change the",
    "actually change", "actually update", "timing",
    # list triggers
    "any reminder", "any reminders", "is there", "are there",
    "do i have", "have i set", "already set", "check reminder",
}


def _get_user_timezone() -> str:
    """
    Phase 16 fix: added diagnostic logging for every fallback path, since
    silent UTC defaulting was the root cause of multiple "wrong reminder
    time" bugs that were invisible in server logs and took many rounds of
    debugging to trace. Now any time this returns "UTC" because the user
    has no saved preference (rather than because they explicitly chose
    UTC), it's logged so the gap is visible immediately instead of only
    showing up as a confusing user-facing symptom.

    Phase 34 fix: even with the above logging, the stored preference
    could still genuinely not have landed yet at the moment a reminder
    was created -- syncTimezoneToBackend() is fire-and-forget and does
    two sequential network round-trips, so a reminder created via chat
    within that window (very plausible right after login) still hit the
    "no preferences row yet" fallback and got permanently created in
    UTC. Now checks the CURRENT request's fresh, race-condition-free
    timezone (sent as the X-Timezone header on every /chat/stream
    request, see api/chat.py) before ever touching the stored
    preference. If that's present, it's used directly -- and
    opportunistically written back to the stored preference too, so
    background jobs with no live request (the proactive engine deciding
    whether it's a reasonable local hour to surface an insight) also
    self-heal without needing their own separate sync path.
    """
    from backend.core.request_context import get_current_request_timezone

    fresh_tz = get_current_request_timezone()
    if fresh_tz:
        _opportunistically_persist_timezone(fresh_tz)
        return fresh_tz

    db = SessionLocal()
    try:
        uid = get_current_user_id()
        if uid is None:
            agent_logger.warning(
                "[ReminderAgent] _get_user_timezone: get_current_user_id() "
                "returned None — falling back to UTC. This means the auth "
                "context did not propagate to this call; reminder times "
                "for this request will be wrong unless the user is "
                "actually in UTC."
            )
            return "UTC"

        row = db.query(UserPreference).filter(
            UserPreference.key == "default",
            UserPreference.user_id == uid,
        ).first()

        if row and row.value:
            prefs = json.loads(row.value)
            tz = prefs.get("timezone")
            if tz:
                return tz
            agent_logger.info(
                f"[ReminderAgent] user {uid} has a preferences row but no "
                f"timezone key set — falling back to UTC. Frontend "
                f"syncTimezoneToBackend() may not have run yet for this user."
            )
            return "UTC"

        agent_logger.info(
            f"[ReminderAgent] user {uid} has no preferences row at all — "
            f"falling back to UTC. This is expected for a brand-new user "
            f"before their first timezone sync completes."
        )
        return "UTC"
    except Exception as e:
        agent_logger.error(f"[ReminderAgent] _get_user_timezone failed: {e}")
        return "UTC"
    finally:
        db.close()


def _opportunistically_persist_timezone(tz_name: str) -> None:
    """Best-effort write-back of a freshly-known-good timezone into the
    stored preference, so paths that only ever check the stored value
    (background jobs with no live request) benefit too. Never raises --
    this is a nice-to-have, not something that should ever break a
    reminder operation if it fails."""
    uid = get_current_user_id()
    if uid is None:
        return
    db = SessionLocal()
    try:
        row = db.query(UserPreference).filter(
            UserPreference.key == "default",
            UserPreference.user_id == uid,
        ).first()
        prefs = {}
        if row and row.value:
            try:
                prefs = json.loads(row.value)
            except Exception:
                prefs = {}
        if prefs.get("timezone") == tz_name:
            return  # already in sync, nothing to write
        prefs["timezone"] = tz_name
        blob = json.dumps(prefs)
        if row:
            row.value = blob
        else:
            row = UserPreference(key="default", value=blob, user_id=uid)
            db.add(row)
        db.commit()
    except Exception as e:
        agent_logger.warning(f"[ReminderAgent] opportunistic timezone persist failed (non-fatal): {e}")
    finally:
        db.close()


def _local_now(tz_name: str) -> str:
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
        now = datetime.now(tz)
        return now.strftime("%A, %d %B %Y, %I:%M %p %Z")
    except Exception:
        return datetime.utcnow().strftime("%A, %d %B %Y, %I:%M %p UTC")


def _to_iso_with_tz(time_str: str, tz_name: str) -> str | None:
    try:
        import zoneinfo
        from dateutil import parser as dp
        tz = zoneinfo.ZoneInfo(tz_name)
        now_local = datetime.now(tz)
        parsed = dp.parse(time_str, default=now_local, fuzzy=True)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        from datetime import timezone as utc_tz
        return parsed.astimezone(utc_tz.utc).isoformat()
    except Exception:
        return None


class ReminderAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "reminder"

    @property
    def description(self) -> str:
        return (
            "Smart reminder agent. Sets, lists, reschedules, and deletes reminders "
            "using natural language. Parses 'next Monday', 'in 3 days', 'change the "
            "time to 1pm', 'delete my study reminder', etc."
        )

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in _REMINDER_KEYWORDS)

    def _detect_intent(self, query: str) -> str:
        """Returns: save | list | reschedule | delete"""
        q = query.lower()

        if any(w in q for w in (
            "list", "show", "what", "my reminder", "upcoming", "pending",
            "any reminder", "any reminders", "do i have", "have i set",
            "is there", "are there", "currently", "already set",
            "check reminder", "see reminder", "view reminder",
            "remind me of", "what reminder", "tell me my",
        )):
            return "list"

        if any(w in q for w in (
            "change the time", "change the timing", "reschedule",
            "move the reminder", "update the reminder",
            "change reminder", "change the reminder",
            "postpone", "push back", "change to", "move to",
            "change it to", "update it to", "make it", "set it to",
            "i would like to change", "i want to change",
            "actually change", "actually update", "actually reschedule",
            "timing", "change it", "update it", "modify it",
        )):
            return "reschedule"

        if any(w in q for w in (
            "delete", "remove", "cancel", "clear", "get rid of",
        )):
            return "delete"

        return "save"

    def _get_all_reminders(self) -> list[dict]:
        db = SessionLocal()
        try:
            user_id = get_current_user_id()
            reminders = db.query(Reminder)\
                .filter(Reminder.user_id == user_id)\
                .order_by(Reminder.id.desc()).all()
            return [
                {
                    "id": r.id,
                    "title": r.title or r.content or "",
                    "content": r.content or "",
                    "due_time": r.due_time or "",
                    "due_at": str(r.due_at) if r.due_at else "",
                }
                for r in reminders
            ]
        finally:
            db.close()

    def _find_reminder_by_ref(self, query: str, reminders: list[dict]) -> dict | None:
        """
        Phase 15: Use conversation history + query to identify which reminder
        the user is referring to. Falls back to most recent if ambiguous.
        """
        if not reminders:
            return None

        # If only one reminder exists, that's almost certainly what they mean
        if len(reminders) == 1:
            return reminders[0]

        history = self.get_conversation_context(turns=6)
        summary = "\n".join(
            f"ID:{r['id']} | Task:{r['title']!r} | When:{r['due_time']}"
            for r in reminders[:10]
        )
        prompt = (
            f"{history}\n"
            f"The user said: {query!r}\n\n"
            f"Existing reminders:\n{summary}\n\n"
            f"Which reminder ID is the user referring to? "
            f"Use conversation history to infer context. "
            f"Return ONLY the numeric ID, nothing else."
        )
        raw = ask_llm_raw(prompt).strip()
        try:
            target_id = int(raw)
            for r in reminders:
                if r["id"] == target_id:
                    return r
        except (ValueError, TypeError):
            pass
        # Fallback: most recent
        return reminders[0]

    # ── Parse new reminder ────────────────────────────────────────────────────

    def _parse_reminder(self, query: str) -> tuple[str | None, str | None]:
        """
        Phase 15 fix: Injects conversation history so "change to 1pm"
        can resolve the task name from a prior turn.
        """
        tz_name = _get_user_timezone()
        now_str = _local_now(tz_name)
        history = self.get_conversation_context(turns=6)

        prompt = (
            f"The user's current local time is: {now_str}\n\n"
            f"{history}\n"
            f"Extract the reminder task and timeframe from this request.\n"
            f"IMPORTANT: If the task isn't stated in the current request but was "
            f"mentioned in the conversation history above, use that task.\n\n"
            f"Return ONLY two lines:\n"
            f"TASK: <the task — or UNKNOWN if truly not determinable>\n"
            f"TIME: <when in natural language — or UNKNOWN if not specified>\n\n"
            f"Request: {query}"
        )
        raw = ask_llm_raw(prompt)
        task: str | None = None
        timeframe: str | None = None

        for line in raw.splitlines():
            line = line.strip()
            if line.upper().startswith("TASK:"):
                val = line.split(":", 1)[-1].strip()
                if val.upper() != "UNKNOWN" and len(val) > 1:
                    task = val
            elif line.upper().startswith("TIME:"):
                val = line.split(":", 1)[-1].strip()
                if val.upper() != "UNKNOWN" and len(val) > 1:
                    timeframe = val

        return task, timeframe

    def _extract_reschedule_intent(self, query: str) -> dict:
        """
        Determine what the user wants to change: time, task, or both.
        Returns dict with keys: new_time, new_task (either can be None).
        """
        tz_name = _get_user_timezone()
        now_str = _local_now(tz_name)
        history = self.get_conversation_context(turns=6)

        prompt = (
            f"Current local time: {now_str}\n"
            f"{history}\n"
            f"The user wants to modify an existing reminder.\n"
            f"Extract what they want to change.\n\n"
            f"Return EXACTLY these lines (use UNKNOWN if not specified):\n"
            f"NEW_TASK: <new task name, or UNKNOWN>\n"
            f"NEW_TIME: <new time in natural language, or UNKNOWN>\n\n"
            f"Request: {query}"
        )
        raw = ask_llm_raw(prompt)
        result = {"new_task": None, "new_time": None}
        for line in raw.splitlines():
            line = line.strip()
            if line.upper().startswith("NEW_TASK:"):
                val = line.split(":", 1)[-1].strip()
                if val.upper() != "UNKNOWN" and len(val) > 1:
                    result["new_task"] = val
            elif line.upper().startswith("NEW_TIME:"):
                val = line.split(":", 1)[-1].strip()
                if val.upper() != "UNKNOWN" and len(val) > 1:
                    result["new_time"] = val
        return result

    def _update_reminder(self, reminder_id: int, new_task: str | None, new_time: str | None) -> bool:
        tz_name = _get_user_timezone()
        db = SessionLocal()
        try:
            uid = get_current_user_id()
            r = db.query(Reminder).filter(
                Reminder.id == reminder_id, Reminder.user_id == uid
            ).first()
            if not r:
                return False
            if new_task:
                r.title = new_task
                r.content = new_task
            if new_time:
                r.due_time = new_time
                due_iso = _to_iso_with_tz(new_time, tz_name)
                if due_iso:
                    r.due_at = due_iso
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()

    # ── DB operations ─────────────────────────────────────────────────────────

    def _reschedule_reminder(self, reminder_id: int, new_time: str) -> bool:
        tz_name = _get_user_timezone()
        due_iso = _to_iso_with_tz(new_time, tz_name)
        db = SessionLocal()
        try:
            uid = get_current_user_id()
            r = db.query(Reminder).filter(
                Reminder.id == reminder_id, Reminder.user_id == uid
            ).first()
            if not r:
                return False
            r.due_time = new_time
            if due_iso:
                r.due_at = due_iso
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()

    def _delete_reminder(self, reminder_id: int) -> bool:
        db = SessionLocal()
        try:
            uid = get_current_user_id()
            r = db.query(Reminder).filter(
                Reminder.id == reminder_id, Reminder.user_id == uid
            ).first()
            if not r:
                return False
            db.delete(r)
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, query: str, context: dict | None = None) -> AgentResult:
        steps = []
        agent_logger.info(f"[ReminderAgent] query={query!r}")

        intent = self._detect_intent(query)
        steps.append(f"Detected intent: {intent}")

        # ── LIST ──────────────────────────────────────────────────────────────
        if intent == "list":
            reminders = self._get_all_reminders()
            if not reminders:
                answer = "You have no reminders set. Ask me to remind you about something!"
            else:
                lines = [
                    f"**{i+1}.** {r['title']} *(Due: {r['due_time']})*"
                    for i, r in enumerate(reminders)
                ]
                answer = f"You have **{len(reminders)} reminder(s)**:\n\n" + "\n\n".join(lines)

        # ── RESCHEDULE ────────────────────────────────────────────────────────
        elif intent == "reschedule":
            steps.append("Finding target reminder…")
            reminders = self._get_all_reminders()
            target = self._find_reminder_by_ref(query, reminders)

            if not target:
                answer = "You don't have any reminders to reschedule."
            else:
                steps.append(f"Target: '{target['title']}' at {target['due_time']}")
                changes = self._extract_reschedule_intent(query)
                new_task = changes.get("new_task")
                new_time = changes.get("new_time")

                if not new_task and not new_time:
                    answer = (
                        f"I found your reminder: **{target['title']}** "
                        f"*(currently set for {target['due_time']})*. What would you like to change it to?"
                    )
                else:
                    ok = self._update_reminder(target["id"], new_task, new_time)
                    if ok:
                        updated_task = new_task or target["title"]
                        updated_time = new_time or target["due_time"]
                        what_changed = []
                        if new_task: what_changed.append(f"task → **{new_task}**")
                        if new_time: what_changed.append(f"time → **{new_time}**")
                        answer = (
                            f"✓ Reminder updated! Changed {' and '.join(what_changed)}.\n\n"
                            f"**Task:** {updated_task}\n**When:** {updated_time}"
                        )
                    else:
                        answer = "I couldn't update that reminder. It may have been deleted."

        # ── DELETE ────────────────────────────────────────────────────────────
        elif intent == "delete":
            steps.append("Finding target reminder…")
            reminders = self._get_all_reminders()
            target = self._find_reminder_by_ref(query, reminders)

            if not target:
                answer = "You don't have any reminders to delete."
            else:
                ok = self._delete_reminder(target["id"])
                answer = (
                    f"✓ Reminder deleted: **{target['title']}** *(was due: {target['due_time']})*"
                    if ok else "I couldn't delete that reminder."
                )

        # ── SAVE ──────────────────────────────────────────────────────────────
        else:
            steps.append("Parsing reminder from natural language…")
            task, timeframe = self._parse_reminder(query)

            if not task and not timeframe:
                return AgentResult(
                    answer=(
                        "I'd be happy to set a reminder! Could you tell me:\n\n"
                        "• **What** should I remind you about?\n"
                        "• **When** should the reminder go off?"
                    ),
                    agent_name=self.name, sources=[], steps=steps, confidence=60,
                )
            if not task:
                return AgentResult(
                    answer="Got the time — but what should I remind you about?",
                    agent_name=self.name, sources=[], steps=steps, confidence=60,
                )
            if not timeframe:
                return AgentResult(
                    answer=f"Got it — remind you about **{task}**. When should I remind you?",
                    agent_name=self.name, sources=[], steps=steps, confidence=60,
                )

            steps.append(f"Extracted: task='{task}' time='{timeframe}'")

            tz_name = _get_user_timezone()
            due_iso = _to_iso_with_tz(timeframe, tz_name)

            result = _reminder_tool.run(f"save:{task}|{timeframe}")

            if "successfully" in result.lower() and due_iso:
                try:
                    db = SessionLocal()
                    uid = get_current_user_id()
                    reminder = (
                        db.query(Reminder)
                        .filter(Reminder.content == task, Reminder.user_id == uid)
                        .order_by(Reminder.id.desc())
                        .first()
                    )
                    if reminder and not reminder.due_at:
                        reminder.due_at = due_iso
                        reminder.title = task
                        db.commit()
                    db.close()
                except Exception:
                    pass

            if "successfully" in result.lower():
                # Phase 34 fix: without this, asking "what are my
                # reminders" right after creating one could answer from
                # a context block cached from before this reminder
                # existed -- see core/llm.py's CONTEXT_CACHE_TTL_SECONDS
                # docstring for the full reasoning. The TTL there is the
                # systemic backstop; this is the instant-correctness
                # version for the single most common reminder flow.
                from backend.core.llm import invalidate_context_cache
                invalidate_context_cache()

                # Phase 24 fix: this used to be a labeled-card template
                # ("✓ Reminder set!\n\n**Task:** X\n**When:** Y") — a hardcoded
                # Python f-string, not something generated by the LLM, so
                # every tone/length rule added to SYSTEM_PROMPT had zero
                # effect on it. It's the single most common action in the
                # app and it looked exactly like the templated-chatbot
                # style the rest of Athena was being tuned away from. A
                # plain sentence matches how a person actually confirms
                # something.
                answer = f"Got it — I'll remind you to {task} {timeframe}."
            elif "already exists" in result.lower():
                answer = f"You already have a reminder to {task}."
            else:
                answer = f"Reminder result: {result}"

        return AgentResult(
            answer=answer,
            agent_name=self.name,
            sources=[],
            steps=steps,
            confidence=90,
            metadata={"intent": intent},
        )

    def run_stream(
        self, query: str, context: dict | None = None
    ) -> Generator[str, None, None]:
        result = self.run(query, context)
        words = result.answer.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")