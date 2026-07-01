"""Phase 22: Add user_actions table (connected actions / webhooks)

Revision ID: 0003_phase22_email_actions
Revises: 0002_phase14_assistant
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_phase22_email_actions"
down_revision = "0002_phase14_assistant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("webhook_url", sa.Text(), nullable=False),
        sa.Column("http_method", sa.String(), nullable=False, server_default="POST"),
        sa.Column("payload_template", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "name", name="uq_user_actions_user_name"),
    )
    op.create_index("ix_user_actions_id", "user_actions", ["id"])
    op.create_index("ix_user_actions_user_id", "user_actions", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_actions")
