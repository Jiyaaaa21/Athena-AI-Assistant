"""phase 31: admin surface -- is_admin flag + audit log

Revision ID: 0005_admin_surface
Revises: 0004_pg_document_storage
Create Date: 2026-07-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005_admin_surface"
down_revision: Union[str, None] = "0004_pg_document_storage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admin_user_id", sa.Integer(), nullable=True),
        sa.Column("admin_email", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("target_email", sa.String(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_admin_audit_log_id"), "admin_audit_log", ["id"], unique=False)
    op.create_index(op.f("ix_admin_audit_log_admin_user_id"), "admin_audit_log", ["admin_user_id"], unique=False)
    op.create_index(op.f("ix_admin_audit_log_target_user_id"), "admin_audit_log", ["target_user_id"], unique=False)
    op.create_index(op.f("ix_admin_audit_log_created_at"), "admin_audit_log", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_audit_log_created_at"), table_name="admin_audit_log")
    op.drop_index(op.f("ix_admin_audit_log_target_user_id"), table_name="admin_audit_log")
    op.drop_index(op.f("ix_admin_audit_log_admin_user_id"), table_name="admin_audit_log")
    op.drop_index(op.f("ix_admin_audit_log_id"), table_name="admin_audit_log")
    op.drop_table("admin_audit_log")

    op.drop_column("users", "is_admin")