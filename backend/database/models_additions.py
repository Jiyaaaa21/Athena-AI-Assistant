# ── APPEND THIS BLOCK TO THE END OF backend/database/models.py ──────────────

# ─────────────────────────────────────────────────────────────────────────────
# Phase 22: Connected Actions (generic outbound webhooks)
# ─────────────────────────────────────────────────────────────────────────────

class UserAction(Base):
    """
    A user-registered outbound webhook Athena can trigger from chat, e.g.
    "run my 'lights on' action" or "post to Slack". `name` is what the
    assistant matches against natural language, so keep it short and
    distinctive (enforced loosely — case-insensitive unique per user).

    `payload_template` is an optional JSON string with `{field}` placeholders
    the LLM fills in from the user's request before sending (e.g.
    '{"text": "{message}"}' for a Slack incoming webhook). If null, the
    webhook is triggered with an empty POST body — fine for simple triggers
    like IFTTT/Home Assistant automations that don't need a payload.

    webhook_url is stored as plaintext, consistent with how
    GoogleCalendarToken stores OAuth tokens today. If this table ever holds
    genuinely sensitive credentials (e.g. a webhook URL with an embedded
    secret token), consider encrypting at rest — out of scope for this pass.
    """
    __tablename__ = "user_actions"

    id                = Column(Integer, primary_key=True, index=True)
    user_id           = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name              = Column(String, nullable=False)
    description       = Column(Text, nullable=True)
    webhook_url       = Column(Text, nullable=False)
    http_method       = Column(String, nullable=False, default="POST")
    payload_template  = Column(Text, nullable=True)
    enabled           = Column(Boolean, nullable=False, default=True)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    created_at        = Column(DateTime(timezone=True), default=utcnow)
    updated_at        = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_actions_user_name"),
    )
