"""Phase 11/12: initial authentication + multi-user schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-24

Creates the complete Athena schema (auth tables + every existing
feature table, now carrying `user_id` ownership) for a *fresh* database --
this is the migration path for a brand new PostgreSQL deployment.

For an existing pre-Phase-12 SQLite dev database that was previously
managed only by backend/database/migrate.py (no Alembic history), do NOT
run this migration against it -- its ADD COLUMN / backfill logic already
performs the equivalent upgrade in place every time the app starts. Once
migrated, you can `alembic stamp 0001_initial_schema` to mark it as
up to date with Alembic going forward without re-running the DDL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Auth tables ───────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("avatar_path", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_refresh_tokens_id", "refresh_tokens", ["id"])
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_password_reset_tokens_id", "password_reset_tokens", ["id"])
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"], unique=True)

    # ── Core feature tables (Phase 1-10), now with user_id ownership ──────
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("content", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
    )
    op.create_index("ix_messages_id", "messages", ["id"])
    op.create_index("ix_messages_user_id", "messages", ["user_id"])

    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("content", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True, server_default=""),
        sa.Column("pinned", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("tags", sa.String(), nullable=True),
    )
    op.create_index("ix_notes_id", "notes", ["id"])
    op.create_index("ix_notes_user_id", "notes", ["user_id"])

    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("content", sa.String(), nullable=True),
        sa.Column("due_time", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True, server_default=""),
        sa.Column("due_at", sa.String(), nullable=True),
        sa.Column("done", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("priority", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
    )
    op.create_index("ix_reminders_id", "reminders", ["id"])
    op.create_index("ix_reminders_user_id", "reminders", ["user_id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("filename", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("pages", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("status", sa.String(), nullable=True, server_default="processed"),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.UniqueConstraint("user_id", "filename", name="uq_documents_user_filename"),
    )
    op.create_index("ix_documents_id", "documents", ["id"])
    op.create_index("ix_documents_user_id", "documents", ["user_id"])
    op.create_index("ix_documents_filename", "documents", ["filename"])
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])

    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("key", sa.String(), nullable=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "key", name="uq_user_preferences_user_key"),
    )
    op.create_index("ix_user_preferences_id", "user_preferences", ["id"])
    op.create_index("ix_user_preferences_user_id", "user_preferences", ["user_id"])
    op.create_index("ix_user_preferences_key", "user_preferences", ["key"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("title", sa.String(), nullable=True, server_default="New Conversation"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.Column("message_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("starred", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("pinned", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("folder_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_conversations_id", "conversations", ["id"])
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
    )
    op.create_index("ix_conversation_messages_id", "conversation_messages", ["id"])
    op.create_index("ix_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"])

    op.create_table(
        "folders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "name", name="uq_folders_user_name"),
    )
    op.create_index("ix_folders_id", "folders", ["id"])
    op.create_index("ix_folders_user_id", "folders", ["user_id"])
    op.create_index("ix_folders_name", "folders", ["name"])

    op.create_table(
        "voice_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("key", sa.String(), nullable=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "key", name="uq_voice_settings_user_key"),
    )
    op.create_index("ix_voice_settings_id", "voice_settings", ["id"])
    op.create_index("ix_voice_settings_user_id", "voice_settings", ["user_id"])
    op.create_index("ix_voice_settings_key", "voice_settings", ["key"])


def downgrade() -> None:
    op.drop_table("voice_settings")
    op.drop_table("folders")
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
    op.drop_table("user_preferences")
    op.drop_table("documents")
    op.drop_table("reminders")
    op.drop_table("notes")
    op.drop_table("messages")
    op.drop_table("password_reset_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
