"""init history_entries and history_embeddings with pgvector

Revision ID: 0001
Revises:
Create Date: 2026-08-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from src.utility.provider import DEFAULT_EMBEDDING_DIM

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sync_accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tier", sa.String, nullable=False, server_default="free"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    op.create_table(
        "users",
        sa.Column("browser_uuid", sa.String, primary_key=True),
        sa.Column(
            "sync_account_id",
            sa.Integer,
            sa.ForeignKey("sync_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    op.create_table(
        "sync_codes",
        sa.Column("code", sa.String(8), primary_key=True),
        sa.Column(
            "sync_account_id",
            sa.Integer,
            sa.ForeignKey("sync_accounts.id"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    # Drives the rate-limit window query in sync_service.generate_code.
    op.create_index(
        "ix_sync_codes_account_created_at",
        "sync_codes",
        ["sync_account_id", "created_at"],
    )

    op.create_table(
        "history_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.String, nullable=False),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("title", sa.String, nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("date", sa.String, nullable=True),
        sa.Column("domain", sa.String, nullable=True),
        sa.Column("folder", sa.String, nullable=True),
        sa.Column("flag", sa.String, nullable=False),
        sa.Column(
            "visited_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "user_id", "url", "flag", name="uq_history_entries_user_url_flag"
        ),
    )
    op.create_index("ix_history_entries_user_id", "history_entries", ["user_id"])
    # Drives the per-(user, flag) recency-ordered eviction scan on every ingest batch.
    op.create_index(
        "ix_history_entries_user_flag_visited_at",
        "history_entries",
        ["user_id", "flag", "visited_at"],
    )

    op.create_table(
        "history_embeddings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "history_entry_id",
            sa.Integer,
            sa.ForeignKey("history_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(DEFAULT_EMBEDDING_DIM), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("history_entry_id", name="uq_history_embeddings_entry_id"),
    )

    # HNSW over IVFFlat: no rebuild-on-growth needed, and per-user datasets
    # here are small enough that build cost is a non-issue (pgvector 0.5.0+).
    op.execute(
        "CREATE INDEX idx_history_embeddings_hnsw ON history_embeddings "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_history_embeddings_hnsw")
    op.drop_table("history_embeddings")
    op.drop_index(
        "ix_history_entries_user_flag_visited_at", table_name="history_entries"
    )
    op.drop_index("ix_history_entries_user_id", table_name="history_entries")
    op.drop_table("history_entries")
    op.drop_index("ix_sync_codes_account_created_at", table_name="sync_codes")
    op.drop_table("sync_codes")
    op.drop_table("users")
    op.drop_table("sync_accounts")
