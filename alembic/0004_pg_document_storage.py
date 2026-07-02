"""phase 25: move document storage + RAG chunks into Postgres

Replaces local-disk storage (data/documents/... for raw PDFs, and
ChromaDB's data/chroma_db for embeddings) with rows in this database.
Both of those local-disk locations are wiped on Render's free tier on
every redeploy, restart, or idle spin-down -- this migration exists to
fix that at zero additional cost, using the persistent Postgres database
(Neon) the app already has.

Revision ID: 0004_pg_document_storage
Revises: 58f3c14121da
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_pg_document_storage"
down_revision: Union[str, None] = "58f3c14121da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("file_data", sa.LargeBinary(), nullable=True))

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_chunks_id"), "document_chunks", ["id"], unique=False)
    op.create_index(op.f("ix_document_chunks_document_id"), "document_chunks", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_chunks_user_id"), "document_chunks", ["user_id"], unique=False)
    op.create_index(op.f("ix_document_chunks_source"), "document_chunks", ["source"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_document_chunks_source"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_user_id"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_id"), table_name="document_chunks")
    op.drop_table("document_chunks")

    op.drop_column("documents", "file_data")