from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from datetime import datetime, timezone


Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 11/12: Auth + Multi-User models
# ─────────────────────────────────────────────────────────────────────────────

class User(Base):
    """
    Phase 11 addition: the account model everything else now hangs off of.

    `email` is the login identifier (case-insensitively unique -- enforced
    in backend/auth/service.py by always storing/comparing it lowercased,
    since SQLite's default collation is case-sensitive and a portable
    case-insensitive UNIQUE INDEX would need a Postgres-specific
    `citext`/expression index).
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(120), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)

    # Profile fields
    bio = Column(Text, nullable=True)
    avatar_path = Column(String(500), nullable=True)  # relative path under AVATAR_UPLOAD_DIR

    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    """
    Phase 11 addition: backs JWT refresh-token rotation.

    Refresh tokens are opaque random strings, never JWTs -- only their
    SHA-256 hash is stored, so a DB leak can't be replayed as a valid
    token. Rotation: /auth/refresh marks the presented token `revoked=True`
    and issues a brand new row, so a stolen-and-reused refresh token is
    detectable (the legitimate client's next refresh will fail because its
    token was already revoked by the attacker's use, or vice versa).
    """

    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    token_hash = Column(String(64), nullable=False, unique=True, index=True)  # sha256 hex digest
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)

    user_agent = Column(String(500), nullable=True)
    ip_address = Column(String(64), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    user = relationship("User", back_populates="refresh_tokens")


class PasswordResetToken(Base):
    """
    Phase 11 addition: backs the Forgot Password / Reset Password flow.

    Same opaque-token-hashed-at-rest pattern as RefreshToken. `used`
    prevents a reset link from being replayed after it's been consumed
    once, independent of `expires_at`.
    """

    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    user = relationship("User", back_populates="password_reset_tokens")


# ─────────────────────────────────────────────────────────────────────────────
# Existing Athena models, now with Phase 12 `user_id` ownership columns.
#
# `user_id` is nullable at the DB level (SQLite can't cheaply ADD COLUMN ...
# NOT NULL with a FK on an existing populated table without a full table
# rebuild). It is always set by the application on every INSERT, and every
# SELECT/UPDATE/DELETE always filters on it -- see core/request_context.py.
# The Alembic migration (alembic/versions/0002_...) backfills any pre-Phase-12
# rows to a deterministic "legacy" user so nothing becomes silently
# inaccessible after upgrade.
# ─────────────────────────────────────────────────────────────────────────────

class Message(Base):

    __tablename__ = "messages"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    # Phase 12 addition: owning user. Indexed since every memory_service
    # query now filters on it.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    role = Column(String)

    content = Column(String)

    # Phase 5 addition: needed so /analytics can show real conversation
    # counts over time. Existing rows from before this column existed will
    # be NULL after migration (we genuinely don't know when they happened),
    # so they count toward lifetime totals but not toward "this week" or
    # the activity trend.
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Note(Base):
    """
    NOTE: `content` is the original column used by the chat-based NotesTool
    (e.g. "save: buy milk"). It is preserved so the existing /chat tool-routing
    flow keeps working unchanged. The REST API (api/notes.py) treats `content`
    as the note "body" and additionally exposes title/pinned/color/created_at,
    which are new columns added for the Notes page UI.
    """

    __tablename__ = "notes"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    # Phase 12 addition: owning user.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    content = Column(String)  # note body (legacy column name, kept for the chat tool)

    title = Column(String, default="")
    pinned = Column(Boolean, default=False)
    color = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Roadmap addition: Note Categories / Note Tags. Both nullable so existing
    # rows (and any insert that omits them) are unaffected. `tags` is stored
    # as a comma-separated string -- simplest thing that works with the
    # existing SQLite migrate.py, which only knows how to ADD COLUMN, not
    # create a separate many-to-many tags table.
    category = Column(String, nullable=True)
    tags = Column(String, nullable=True)


class Reminder(Base):
    """
    NOTE: `content` / `due_time` are the original columns used by the
    chat-based ReminderTool (free-text due times like "Friday"). They are
    preserved so /chat keeps working unchanged. The REST API additionally
    uses title/due_at/done/priority for the Reminders page UI, where due_at
    is always a real ISO-8601 datetime (required by a <input type="datetime-local">
    picker on the frontend).
    """

    __tablename__ = "reminders"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    # Phase 12 addition: owning user.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    content = Column(String)  # legacy column, kept for the chat tool

    due_time = Column(String)  # legacy column, kept for the chat tool (free text e.g. "Friday")

    title = Column(String, default="")
    due_at = Column(String, nullable=True)  # ISO-8601 string
    done = Column(Boolean, default=False)
    priority = Column(String, nullable=True)  # "low" | "med" | "high"

    # Roadmap addition: Reminder Categories. Nullable, additive.
    category = Column(String, nullable=True)


class Document(Base):
    """
    New table. Did not exist before Phase 2 — the original /upload-document
    endpoint wrote files to disk and embeddings to ChromaDB but never recorded
    a row anywhere, so there was no way to list or delete documents. This is
    the backing store for GET/DELETE /documents.

    Phase 12 change: `filename` uniqueness is now scoped per-user (two
    different users can both upload "resume.pdf") via the composite
    UniqueConstraint below, instead of the old globally-unique column.
    """

    __tablename__ = "documents"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    # Phase 12 addition: owning user.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    filename = Column(String, index=True)
    size_bytes = Column(Integer, default=0)
    pages = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0)
    status = Column(String, default="processed")  # "processing" | "processed" | "failed"
    uploaded_at = Column(DateTime(timezone=True), default=utcnow)
    # Phase 7 addition: SHA-256 of the file's bytes, used to detect true
    # duplicates (same content, possibly under a different filename) so a
    # re-upload doesn't waste an embedding pass or create redundant chunks.
    # Phase 12: dedup is scoped per-user (see api/upload.py) -- one user's
    # upload must never short-circuit because a *different* user happened
    # to upload byte-identical content.
    content_hash = Column(String, nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("user_id", "filename", name="uq_documents_user_filename"),
    )


class UserPreference(Base):
    """
    Phase 4.5 addition: stores user preferences as a JSON blob under a named
    key. A single row keyed "default" holds all settings for now. Using a
    key-value store rather than individual columns keeps future settings
    additive with zero migrations.

    Phase 12 change: `key` uniqueness is now scoped per-user via the
    composite UniqueConstraint (every user has their own "default" row),
    instead of one global "default" row shared by everyone.
    """

    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, index=True)

    # Phase 12 addition: owning user.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    key = Column(String, index=True)   # always "default" for now
    value = Column(Text)                             # JSON blob
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_preferences_user_key"),
    )


class Conversation(Base):
    """
    Phase 8: Conversation Management System.
    Each conversation groups a set of messages under a named thread.
    """

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)

    # Phase 12 addition: owning user.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    title = Column(String, default="New Conversation")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    message_count = Column(Integer, default=0)
    starred = Column(Boolean, default=False)
    pinned = Column(Boolean, default=False)
    folder_id = Column(Integer, nullable=True)   # FK to Folder.id (soft ref)


class ConversationMessage(Base):
    """
    Phase 8: Per-conversation message storage (separate from global messages
    table to avoid disrupting the existing memory/chat pipeline).

    No direct `user_id` column: ownership is derived through
    `conversation_id -> Conversation.user_id`, since a conversation message
    never makes sense without its parent conversation. API handlers join
    through Conversation to enforce isolation (see api/conversations.py).
    """

    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role = Column(String)          # "user" | "assistant"
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Folder(Base):
    """
    Phase 8: Conversation Folders for organisation.

    Phase 12 change: `name` uniqueness is now scoped per-user via the
    composite UniqueConstraint, instead of a single global namespace.
    """

    __tablename__ = "folders"

    id = Column(Integer, primary_key=True, index=True)

    # Phase 12 addition: owning user.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    name = Column(String, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_folders_user_name"),
    )


class VoiceSettings(Base):
    """
    Phase 9 addition: persists voice preferences for the Voice OS.
    Uses key-value JSON like UserPreference to stay migration-light.

    Phase 12 change: `key` uniqueness is now scoped per-user, same pattern
    as UserPreference.
    """

    __tablename__ = "voice_settings"

    id = Column(Integer, primary_key=True, index=True)

    # Phase 12 addition: owning user.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    key = Column(String, index=True)   # always "default"
    value = Column(Text)                             # JSON blob
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_voice_settings_user_key"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 14 (Assistant Transformation): Goals + Projects + Relationship Graph
# ─────────────────────────────────────────────────────────────────────────────

class Goal(Base):
    """
    Phase 14: User goals that Athena tracks and factors into all responses.
    Supports short / medium / long timeframes.
    """
    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    timeframe = Column(String, default="medium")   # "short" | "medium" | "long"
    status = Column(String, default="active")       # "active" | "completed" | "paused"
    progress = Column(Integer, default=0)           # 0-100
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Project(Base):
    """
    Phase 14: Projects group related conversations, notes, reminders, documents.
    Auto-detected by Athena from topics OR manually created by the user.
    """
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default="active")   # "active" | "archived"
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_projects_user_name"),
    )


class ProjectLink(Base):
    """
    Phase 14: Relationship graph — links any entity to a project.
    entity_type: "conversation" | "note" | "reminder" | "document" | "memory"
    entity_id:   the PK of that entity in its table.
    """
    __tablename__ = "project_links"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_project_links_entity", "entity_type", "entity_id"),
    )

# ─────────────────────────────────────────────────────────────────────────────
# Phase 16: Memory Intelligence + Agent Logging + Notifications
# ─────────────────────────────────────────────────────────────────────────────

class UserFact(Base):
    """
    Phase 16: Semantic long-term memory.
    Extracted from conversations by the memory intelligence engine.
    Examples: "user is preparing for GATE 2027", "prefers concise answers",
    "studying in Gurgaon", "working on Athena project".
    
    These are injected into every LLM system prompt so Athena remembers
    the user across sessions, even after the 20-message rolling window drops
    old conversations.
    """
    __tablename__ = "user_facts"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    fact        = Column(Text, nullable=False)          # "User is preparing for GATE 2027"
    category    = Column(String, nullable=True)         # "goal" | "preference" | "context" | "skill"
    confidence  = Column(Integer, default=80)           # 0-100
    source_conv = Column(Integer, nullable=True)        # conversation_id it came from
    created_at  = Column(DateTime(timezone=True), default=utcnow)
    updated_at  = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    active      = Column(Boolean, default=True)         # False = user deleted/overridden


class AgentCallLog(Base):
    """
    Phase 16: Proper agent/tool call logging.
    Previously analytics inferred tool usage from message text keywords —
    fragile and inaccurate. Now every agent invocation is logged here.
    """
    __tablename__ = "agent_call_logs"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    agent_name  = Column(String, nullable=False)       # "reminder" | "note" | "rag" | etc.
    query       = Column(Text, nullable=True)
    success     = Column(Boolean, default=True)
    latency_ms  = Column(Integer, nullable=True)
    conv_id     = Column(Integer, nullable=True)
    created_at  = Column(DateTime(timezone=True), default=utcnow)


class ReminderFired(Base):
    """
    Phase 16: Track which reminders have been fired so the scheduler
    doesn't fire the same reminder twice.
    """
    __tablename__ = "reminders_fired"

    id          = Column(Integer, primary_key=True, index=True)
    reminder_id = Column(Integer, ForeignKey("reminders.id", ondelete="CASCADE"), unique=True)
    fired_at    = Column(DateTime(timezone=True), default=utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 18: Timers (distinct from Reminders — short-duration, audible alarm,
# countdown-driven rather than scheduled-datetime-driven)
# ─────────────────────────────────────────────────────────────────────────────

class Timer(Base):
    """
    A short-duration countdown timer with an audible alarm, distinct from
    Reminder. Reminders are scheduled for a specific future datetime and
    fire silently as a notification; Timers count down from a duration
    ("10 minutes") and ring with sound when they hit zero — the classic
    "set a timer for pasta" voice-assistant command.
    """
    __tablename__ = "timers"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label       = Column(String, nullable=True)          # "pasta", "laundry" — optional
    duration_seconds = Column(Integer, nullable=False)
    ends_at     = Column(DateTime(timezone=True), nullable=False)
    status      = Column(String, default="running")      # "running" | "paused" | "finished" | "cancelled"
    remaining_seconds_at_pause = Column(Integer, nullable=True)  # set when paused
    created_at  = Column(DateTime(timezone=True), default=utcnow)


class Routine(Base):
    """
    Phase 18: A named sequence of actions triggered by one phrase —
    "Hey Athena, good morning" running weather + reminders + goals in
    one shot, the way Alexa/Siri Routines/Shortcuts work.

    steps is stored as a JSON array of strings, each one a natural-
    language query run through the normal agent orchestrator in order;
    results are concatenated into one combined response.
    """
    __tablename__ = "routines"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name        = Column(String, nullable=False)          # "Good Morning"
    trigger_phrase = Column(String, nullable=False)       # "good morning" — matched loosely
    steps       = Column(Text, nullable=False)             # JSON array of query strings
    enabled     = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), default=utcnow)
    updated_at  = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 20: Google Calendar integration
# ─────────────────────────────────────────────────────────────────────────────

class GoogleCalendarToken(Base):
    """
    Stores each user's Google OAuth tokens for Calendar API access.
    access_token is short-lived (~1hr); refresh_token is long-lived and
    used to silently mint new access tokens without re-prompting consent.
    One row per user — connecting again overwrites the existing row.
    """
    __tablename__ = "google_calendar_tokens"

    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    access_token  = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)   # may be absent on token refresh responses
    token_expiry  = Column(DateTime(timezone=True), nullable=True)
    scope         = Column(Text, nullable=True)
    google_email  = Column(String, nullable=True)  # which Google account is connected, shown in Settings
    connected_at  = Column(DateTime(timezone=True), default=utcnow)
    updated_at    = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
