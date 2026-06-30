"""Phase 14: Add goals, projects, project_links tables

Revision ID: 0002_phase14_assistant
Revises: 0001_initial_schema
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_phase14_assistant"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Goals ─────────────────────────────────────────────────────────────────
    op.create_table(
        "goals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("timeframe", sa.String(), nullable=True, server_default="medium"),
        sa.Column("status", sa.String(), nullable=True, server_default="active"),
        sa.Column("progress", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
    )
    op.create_index("ix_goals_id", "goals", ["id"])
    op.create_index("ix_goals_user_id", "goals", ["user_id"])

    # ── Projects ──────────────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=True, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "name", name="uq_projects_user_name"),
    )
    op.create_index("ix_projects_id", "projects", ["id"])
    op.create_index("ix_projects_user_id", "projects", ["user_id"])

    # ── Project Links (Relationship Graph) ────────────────────────────────────
    op.create_table(
        "project_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
    )
    op.create_index("ix_project_links_id", "project_links", ["id"])
    op.create_index("ix_project_links_project_id", "project_links", ["project_id"])
    op.create_index("ix_project_links_entity", "project_links", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_table("project_links")
    op.drop_table("projects")
    op.drop_table("goals")