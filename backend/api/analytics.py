"""
Analytics API — Phase 5 complete rewrite (additive, same endpoint path).

New fields added to GET /analytics response:
  messages_sent          – total messages (user + assistant)
  tool_usage             – per-tool call counts derived from assistant messages
  top_features           – ranked list of most-used features
  weekly_trend           – 8 weeks of per-week totals
  monthly_trend          – 12 months of per-month totals
  heatmap                – 84-day day-of-week × hour-of-day activity grid
  hourly_distribution    – 24-bucket message count by hour of day
  streak                 – current daily active streak in days
  avg_messages_per_day   – rolling 30-day average

All existing fields are preserved unchanged so nothing breaks.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dateutil import parser as date_parser
from fastapi import APIRouter

from backend.database.db import SessionLocal
from backend.database.models import Message, Document, Note, Reminder
from backend.core.request_context import get_current_user_id
from backend.api.reminders import best_effort_iso

router = APIRouter()

WEEK = timedelta(days=7)
DUE_SOON_WINDOW = timedelta(hours=48)
TREND_DAYS = 14
HEATMAP_DAYS = 84        # 12 weeks
WEEKLY_WEEKS = 8
MONTHLY_MONTHS = 12


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── Tool usage inference ──────────────────────────────────────────────────────
# We don't have a dedicated tool_calls table, so we infer from assistant
# message content.  The keywords below are distinctive enough to avoid
# false positives while covering normal usage.

_TOOL_SIGNALS: dict[str, list[str]] = {
    "calculator":  ["= ", "result:", "calculated"],
    "rag":         ["based on the document", "according to", "from the pdf", "the document says"],
    "weather":     ["°c", "°f", "humidity", "forecast", "temperature"],
    "news":        ["headline", "article", "published", "according to the news", "latest news"],
    "notes":       ["note saved", "i've saved", "note added", "added a note"],
    "reminder":    ["reminder set", "i've set a reminder", "reminder added", "remind you"],
}


def _count_tool_usage(assistant_messages: list) -> dict[str, int]:
    counts: dict[str, int] = {t: 0 for t in _TOOL_SIGNALS}
    for msg in assistant_messages:
        lo = (msg.content or "").lower()
        for tool, signals in _TOOL_SIGNALS.items():
            if any(s in lo for s in signals):
                counts[tool] += 1
    return counts


# ── Streak calculation ────────────────────────────────────────────────────────

def _active_streak(user_messages: list, today: datetime) -> int:
    """Count consecutive days (ending today or yesterday) that had ≥1 message."""
    active_days: set = set()
    for m in user_messages:
        if m.created_at:
            active_days.add(_aware(m.created_at).date())
    streak = 0
    check = today.date()
    while check in active_days:
        streak += 1
        check -= timedelta(days=1)
    # If today has no messages yet, count from yesterday
    if streak == 0:
        check = today.date() - timedelta(days=1)
        while check in active_days:
            streak += 1
            check -= timedelta(days=1)
    return streak


# ── Main endpoint ─────────────────────────────────────────────────────────────

@router.get("/analytics")
def get_analytics():
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        week_ago = now - WEEK

        # ── Raw data pulls (Phase 12: scoped to the current user) ─────────
        uid = get_current_user_id()
        all_messages = db.query(Message).filter(Message.user_id == uid).all()
        user_messages = [m for m in all_messages if m.role == "user"]
        assistant_messages = [m for m in all_messages if m.role == "assistant"]

        documents = db.query(Document).filter(Document.user_id == uid).all()
        notes = db.query(Note).filter(Note.user_id == uid).all()
        reminders = db.query(Reminder).filter(Reminder.user_id == uid).all()

        # ── KPI counts ───────────────────────────────────────────────────
        conversations_total = len(user_messages)
        conversations_this_week = sum(
            1 for m in user_messages
            if m.created_at and _aware(m.created_at) >= week_ago
        )

        messages_sent_total = len(all_messages)

        documents_total = len(documents)
        documents_this_week = sum(
            1 for d in documents
            if d.uploaded_at and _aware(d.uploaded_at) >= week_ago
        )

        notes_total = len(notes)
        notes_this_week = sum(
            1 for n in notes
            if n.created_at and _aware(n.created_at) >= week_ago
        )

        reminders_total = len(reminders)
        reminders_this_week = sum(
            1 for r in reminders
            if r.done is False
        )  # active reminders

        due_soon = 0
        for r in reminders:
            if r.done:
                continue
            try:
                due = _aware(date_parser.parse(best_effort_iso(r.due_at, r.due_time)))
            except Exception:
                continue
            if now <= due <= now + DUE_SOON_WINDOW:
                due_soon += 1

        # ── 14-day activity trend (existing) ─────────────────────────────
        buckets_14 = {
            (now - timedelta(days=i)).date(): {"conversations": 0, "documents": 0, "notes": 0}
            for i in range(TREND_DAYS - 1, -1, -1)
        }
        for m in user_messages:
            if m.created_at:
                day = _aware(m.created_at).date()
                if day in buckets_14:
                    buckets_14[day]["conversations"] += 1
        for d in documents:
            if d.uploaded_at:
                day = _aware(d.uploaded_at).date()
                if day in buckets_14:
                    buckets_14[day]["documents"] += 1
        for n in notes:
            if n.created_at:
                day = _aware(n.created_at).date()
                if day in buckets_14:
                    buckets_14[day]["notes"] += 1
        activity = [
            {"date": day.isoformat(), **counts}
            for day, counts in sorted(buckets_14.items())
        ]

        # ── Weekly trend (8 weeks) ────────────────────────────────────────
        def _week_start(dt: datetime):
            d = _aware(dt).date()
            return d - timedelta(days=d.weekday())

        weekly: dict = {}
        for i in range(WEEKLY_WEEKS - 1, -1, -1):
            ws = (now - timedelta(weeks=i)).date()
            ws = ws - timedelta(days=ws.weekday())
            weekly[ws] = {"conversations": 0, "documents": 0, "notes": 0, "reminders": 0}

        for m in user_messages:
            if m.created_at:
                ws = _week_start(m.created_at)
                if ws in weekly:
                    weekly[ws]["conversations"] += 1
        for d in documents:
            if d.uploaded_at:
                ws = _week_start(d.uploaded_at)
                if ws in weekly:
                    weekly[ws]["documents"] += 1
        for n in notes:
            if n.created_at:
                ws = _week_start(n.created_at)
                if ws in weekly:
                    weekly[ws]["notes"] += 1

        weekly_trend = [
            {"week": ws.isoformat(), "label": ws.strftime("W%U %b"), **counts}
            for ws, counts in sorted(weekly.items())
        ]

        # ── Monthly trend (12 months) ────────────────────────────────────
        monthly: dict = {}
        for i in range(MONTHLY_MONTHS - 1, -1, -1):
            # first day of month i months ago
            d = now.replace(day=1)
            month = d.month - i
            year = d.year
            while month <= 0:
                month += 12
                year -= 1
            key = (year, month)
            monthly[key] = {"conversations": 0, "documents": 0, "notes": 0}

        for m in user_messages:
            if m.created_at:
                a = _aware(m.created_at)
                key = (a.year, a.month)
                if key in monthly:
                    monthly[key]["conversations"] += 1
        for d in documents:
            if d.uploaded_at:
                a = _aware(d.uploaded_at)
                key = (a.year, a.month)
                if key in monthly:
                    monthly[key]["documents"] += 1
        for n in notes:
            if n.created_at:
                a = _aware(n.created_at)
                key = (a.year, a.month)
                if key in monthly:
                    monthly[key]["notes"] += 1

        monthly_trend = [
            {
                "month": f"{y}-{m:02d}",
                "label": datetime(y, m, 1).strftime("%b %Y"),
                **counts,
            }
            for (y, m), counts in sorted(monthly.items())
        ]

        # ── Heatmap: 84-day day-of-week × hour grid ───────────────────────
        # heatmap[weekday 0-6][hour 0-23] = count
        heatmap: list[list[int]] = [[0] * 24 for _ in range(7)]
        cutoff = now - timedelta(days=HEATMAP_DAYS)
        for m in user_messages:
            if m.created_at:
                a = _aware(m.created_at)
                if a >= cutoff:
                    heatmap[a.weekday()][a.hour] += 1
        heatmap_out = [
            {"day": i, "dayLabel": ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][i], "hours": row}
            for i, row in enumerate(heatmap)
        ]

        # ── Hourly distribution ───────────────────────────────────────────
        hourly = [0] * 24
        for m in all_messages:
            if m.created_at:
                hourly[_aware(m.created_at).hour] += 1
        hourly_distribution = [{"hour": h, "count": hourly[h]} for h in range(24)]

        # ── Tool usage ────────────────────────────────────────────────────
        tool_counts = _count_tool_usage(assistant_messages)
        tool_usage = [
            {"tool": tool, "count": cnt}
            for tool, cnt in sorted(tool_counts.items(), key=lambda x: -x[1])
        ]

        # ── Top features ──────────────────────────────────────────────────
        feature_counts = {
            "Chat": conversations_total,
            "Notes": notes_total,
            "Reminders": reminders_total,
            "Documents": documents_total,
            "Weather": tool_counts.get("weather", 0),
            "News": tool_counts.get("news", 0),
            "Calculator": tool_counts.get("calculator", 0),
            "RAG Search": tool_counts.get("rag", 0),
        }
        total_fc = sum(feature_counts.values()) or 1
        top_features = [
            {"feature": k, "count": v, "pct": round(v / total_fc * 100, 1)}
            for k, v in sorted(feature_counts.items(), key=lambda x: -x[1])
            if v > 0
        ][:6]

        # ── Streak + avg ──────────────────────────────────────────────────
        streak = _active_streak(user_messages, now)

        last_30 = now - timedelta(days=30)
        msgs_30 = sum(
            1 for m in user_messages
            if m.created_at and _aware(m.created_at) >= last_30
        )
        avg_per_day = round(msgs_30 / 30, 1)

        # ── Response ─────────────────────────────────────────────────────
        return {
            # existing fields (unchanged shape)
            "conversations": {
                "total": conversations_total,
                "thisWeek": conversations_this_week,
            },
            "documents": {
                "total": documents_total,
                "thisWeek": documents_this_week,
            },
            "notes": {
                "total": notes_total,
                "thisWeek": notes_this_week,
            },
            "reminders": {
                "total": reminders_total,
                "dueSoon": due_soon,
            },
            "activity": activity,
            # Phase 5 additions
            "messages_sent": {
                "total": messages_sent_total,
                "thisWeek": sum(
                    1 for m in all_messages
                    if m.created_at and _aware(m.created_at) >= week_ago
                ),
            },
            "tool_usage": tool_usage,
            "top_features": top_features,
            "weekly_trend": weekly_trend,
            "monthly_trend": monthly_trend,
            "heatmap": heatmap_out,
            "hourly_distribution": hourly_distribution,
            "streak": streak,
            "avg_messages_per_day": avg_per_day,
            "reminders_active": reminders_this_week,
        }

    finally:
        db.close()
