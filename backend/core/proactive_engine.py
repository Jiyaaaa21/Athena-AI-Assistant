"""
backend/core/proactive_engine.py  —  Phase 23

Proactive Intelligence: the part of "the intelligence layer" that lets
Athena surface something *unprompted* instead of only ever responding to
a message the user typed.

Mirrors core/reminder_scheduler.py's shape deliberately (background
thread, polls on an interval, delivers via push) but the trigger
condition is fundamentally different: a Reminder fires because the user
explicitly asked to be reminded of something at a specific time. A
ProactiveInsight fires because the *engine itself* decided, by looking
at the user's own context, that something is worth mentioning right now
even though nobody asked.

Per cycle, for every active user:
  1. Skip if they got an insight too recently (PROACTIVE_MIN_GAP_MINUTES
     cooldown) -- the whole point is occasional, relevant nudges, not a
     notification every 15 minutes.
  2. Assemble a context snapshot: goals, overdue reminders, upcoming
     reminders, recent notes/topics (via the existing
     core/context_builder.build_user_context(), Phase 14) plus calendar
     events in the next 2 hours if Google Calendar is connected (Phase 20).
  3. Ask the LLM, as a structured decision (not a chat reply): given this
     context, is there something worth proactively telling this person
     right now? If yes, a short (<200 char) message plus a `kind` label.
  4. If yes: persist a ProactiveInsight row and fire a push notification
     through the same delivery path reminders already use
     (core/push_notifications.send_push_to_user, Phase 21) so it reaches
     the person even if Athena isn't open in a tab.

This is intentionally conservative -- an assistant that pings you
constantly gets muted or uninstalled. Silence is the default outcome of
each cycle; a generated insight is the exception.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

from backend.core.logger import agent_logger
from backend.core.config import (
    PROACTIVE_ENABLED, PROACTIVE_INTERVAL_SECONDS, PROACTIVE_MIN_GAP_MINUTES,
)

_running = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_upcoming_calendar_events(user_id: int) -> list[str]:
    """
    Best-effort: events in the next 2 hours, formatted as short strings.
    Returns [] if Calendar isn't connected or the API call fails -- this
    is a nice-to-have context signal, never something worth crashing a
    background cycle over.
    """
    try:
        from backend.integrations.google_calendar import is_connected, list_events
        if not is_connected(user_id):
            return []
        now = _utcnow()
        events = list_events(user_id, now, now + timedelta(hours=2), max_results=5)
        out = []
        for e in events:
            if e.get("allDay"):
                continue
            out.append(f"{e.get('title', '(untitled)')} at {e.get('start', '?')}")
        return out
    except Exception:
        return []


def _last_insight_at(db, user_id: int):
    from backend.database.models import ProactiveInsight
    row = (
        db.query(ProactiveInsight)
        .filter(ProactiveInsight.user_id == user_id)
        .order_by(ProactiveInsight.created_at.desc())
        .first()
    )
    return row.created_at if row else None


def _build_decision_prompt(ctx: dict, calendar_events: list[str]) -> str:
    def fmt(items):
        return "\n".join(f"  - {i}" for i in items) if items else "  (none)"

    return (
        "You are Athena's proactive-intelligence engine. You do not talk to the "
        "user directly -- you decide, silently, whether Athena should interrupt "
        "them right now with something useful, based on their own data below.\n\n"
        f"Upcoming calendar events (next 2 hours):\n{fmt(calendar_events)}\n\n"
        f"Overdue reminders:\n{fmt(ctx.get('overdue_reminders'))}\n\n"
        f"Upcoming reminders:\n{fmt(ctx.get('pending_reminders'))}\n\n"
        f"Active goals:\n{fmt(ctx.get('goals'))}\n\n"
        f"Active projects:\n{fmt(ctx.get('projects'))}\n\n"
        f"Recent conversation topics:\n{fmt(ctx.get('recent_topics'))}\n\n"
        "Rules:\n"
        "1. Only decide to notify if there's something GENUINELY time-relevant or "
        "actionable right now -- a meeting starting soon, a reminder that's overdue, "
        "a goal that's been untouched a long time and ties to what they were just "
        "discussing. Do NOT invent urgency that isn't in the data above.\n"
        "2. If nothing here clears that bar, decide not to notify. Silence is the "
        "correct, default answer most of the time.\n"
        "3. If you do notify, the message must be short (under 200 characters), "
        "written the way Athena would actually say it out loud -- warm, direct, "
        "no filler like \"I noticed that...\".\n\n"
        "Respond with ONLY a JSON object, nothing else, in exactly this shape:\n"
        '{"should_notify": true or false, "kind": "calendar_soon" | "reminder_upcoming" '
        '| "goal_stale" | "pattern" | "general", "message": "...", '
        '"reason": "one short sentence on WHY you decided this way, always included '
        'even when should_notify is false -- this is never shown to the user, it\'s '
        'for debugging"}'
    )


def _decide_for_user(ctx: dict, calendar_events: list[str]) -> tuple[dict | None, str]:
    """
    Returns (insight_dict_or_None, debug_reason). debug_reason is always a
    human-readable string explaining the outcome -- logged, and surfaced
    through POST /proactive/trigger, so "nothing happened" during manual
    testing is never a dead end.
    """
    from backend.core.llm import ask_llm_raw

    if not (ctx.get("overdue_reminders") or ctx.get("pending_reminders")
            or ctx.get("goals") or calendar_events):
        # Nothing worth even asking the LLM about -- cheap skip, saves a
        # Groq call for users with an empty/quiet context this cycle.
        return None, "no_context: no overdue/upcoming reminders, goals, or soon calendar events found"

    # Ground-truth log of exactly what's being sent to the LLM. The
    # model's own "reason" text (logged separately below) is a paraphrase
    # it generates, not a reliable record of what it was actually shown --
    # if a decline looks wrong, this line is the one to check first.
    agent_logger.info(
        f"[Proactive] context sent to LLM: "
        f"overdue={ctx.get('overdue_reminders')!r}, "
        f"pending={ctx.get('pending_reminders')!r}, "
        f"goals={ctx.get('goals')!r}, "
        f"calendar={calendar_events!r}"
    )

    raw = ask_llm_raw(_build_decision_prompt(ctx, calendar_events)).strip()
    # Strip accidental ```json fences -- small models sometimes add them
    # even when told "JSON only".
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except Exception:
        agent_logger.warning(f"[Proactive] non-JSON decision, skipping: {raw[:300]!r}")
        return None, f"parse_error: LLM response wasn't valid JSON: {raw[:200]!r}"

    llm_reason = (parsed.get("reason") or "").strip()

    if not parsed.get("should_notify"):
        return None, f"llm_declined: {llm_reason or '(no reason given)'}"

    message = (parsed.get("message") or "").strip()
    if not message:
        return None, "llm_declined: should_notify was true but message was empty"

    kind = parsed.get("kind") or "general"
    if kind not in ("calendar_soon", "reminder_upcoming", "goal_stale", "pattern", "general"):
        kind = "general"

    return {"message": message[:300], "kind": kind}, f"generated: {llm_reason or '(no reason given)'}"


def _process_user(db, user_id: int) -> tuple[str, "ProactiveInsight | None"]:
    """
    Returns (outcome, insight_or_None). outcome is one of:
      "cooldown"      -- last insight for this user is too recent
      "no_context"    -- nothing in their data cleared the cheap pre-filter
      "parse_error"   -- the LLM's decision wasn't valid JSON
      "llm_declined"  -- the LLM looked at the context and said no
      "error"         -- an exception occurred (context build or decision call)
      "generated"     -- a new ProactiveInsight was created (and insight is set)
    """
    from backend.database.models import ProactiveInsight
    from backend.core.request_context import set_current_user_id
    from backend.core.context_builder import build_user_context
    from backend.core.push_notifications import send_push_to_user

    last_at = _last_insight_at(db, user_id)
    if last_at is not None:
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        remaining = timedelta(minutes=PROACTIVE_MIN_GAP_MINUTES) - (_utcnow() - last_at)
        if remaining.total_seconds() > 0:
            agent_logger.info(
                f"[Proactive] user {user_id}: cooldown active, "
                f"{int(remaining.total_seconds() // 60)} min remaining"
            )
            return "cooldown", None

    # build_user_context() reads the current-user contextvar rather than
    # taking a user_id param directly (it's normally called mid-request,
    # see core/request_context.py) -- setting it here scopes the call to
    # this user for the rest of this background-thread iteration.
    set_current_user_id(user_id)
    try:
        ctx = build_user_context()
    except Exception as e:
        agent_logger.warning(f"[Proactive] context build failed for user {user_id}: {e}")
        return "error", None

    calendar_events = _get_upcoming_calendar_events(user_id)

    try:
        decision, debug_reason = _decide_for_user(ctx, calendar_events)
    except Exception as e:
        agent_logger.warning(f"[Proactive] decision failed for user {user_id}: {e}")
        return "error", None

    agent_logger.info(f"[Proactive] user {user_id}: {debug_reason}")

    if decision is None:
        return debug_reason.split(":", 1)[0], None

    insight = ProactiveInsight(
        user_id=user_id,
        kind=decision["kind"],
        message=decision["message"],
        delivered=False,
    )
    db.add(insight)
    db.commit()
    db.refresh(insight)

    try:
        # calendar_soon / reminder_upcoming are time-critical (a meeting or
        # deadline is imminent) -- worth requireInteraction so it doesn't
        # auto-hide before being seen. goal_stale/pattern/general are
        # gentler nudges, fine to auto-dismiss like a normal notification.
        urgent = decision["kind"] in ("calendar_soon", "reminder_upcoming")
        sent = send_push_to_user(user_id, title="Athena", body=decision["message"], url="/", urgent=urgent)
        if sent:
            insight.delivered = True
            db.commit()
    except Exception as e:
        agent_logger.error(f"[Proactive] push send failed for user {user_id}: {e}")

    agent_logger.info(f"[Proactive] insight generated for user {user_id}: {decision['kind']!r}")
    return "generated", insight


def run_cycle() -> int:
    """
    Runs one full evaluation pass over every active user. Returns the
    number of insights generated. Exposed as a standalone function (not
    just the private loop below) so POST /proactive/trigger can call it
    on-demand for a single request-scoped test, same pattern as
    /push/test.
    """
    from backend.database.db import SessionLocal
    from backend.database.models import User

    generated = 0
    db = SessionLocal()
    try:
        user_ids = [u.id for u in db.query(User.id).filter(User.is_active == True).all()]
    finally:
        db.close()

    for uid in user_ids:
        db = SessionLocal()
        try:
            outcome, _insight = _process_user(db, uid)
            if outcome == "generated":
                generated += 1
        except Exception as e:
            agent_logger.error(f"[Proactive] cycle failed for user {uid}: {e}")
        finally:
            db.close()

    return generated


def _loop():
    global _running
    agent_logger.info(
        f"[Proactive] engine started (interval={PROACTIVE_INTERVAL_SECONDS}s, "
        f"cooldown={PROACTIVE_MIN_GAP_MINUTES}min)"
    )
    while _running:
        try:
            n = run_cycle()
            if n:
                agent_logger.info(f"[Proactive] cycle complete: {n} insight(s) generated")
        except Exception as e:
            agent_logger.error(f"[Proactive] cycle error: {e}")
        for _ in range(PROACTIVE_INTERVAL_SECONDS):
            if not _running:
                break
            time.sleep(1)
    agent_logger.info("[Proactive] engine stopped")


def start_engine():
    """Call from main.py on_startup. Idempotent. No-op if PROACTIVE_ENABLED=false."""
    global _running
    if not PROACTIVE_ENABLED:
        agent_logger.info("[Proactive] engine disabled (PROACTIVE_ENABLED=false)")
        return
    if _running:
        return
    _running = True
    t = threading.Thread(target=_loop, daemon=True, name="proactive-engine")
    t.start()


def stop_engine():
    global _running
    _running = False