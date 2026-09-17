"""replace flat history_entries with pages / page_sections / section_embeddings

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from src.utility.provider import DEFAULT_EMBEDDING_DIM

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Clean cutover — no backfill. The parent unit moves from "one row per
    # section, loosely tied by url" to a real page/section hierarchy, so
    # the cap and retrieval both key off page count instead of section count.
    op.execute("DROP INDEX IF EXISTS idx_history_embeddings_hnsw")
    op.drop_table("history_embeddings")
    op.drop_index(
        "ix_history_entries_user_flag_visited_at", table_name="history_entries"
    )
    op.drop_index("ix_history_entries_user_id", table_name="history_entries")
    op.drop_table("history_entries")

    op.create_table(
        "pages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("sync_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("title", sa.String, nullable=True),
        sa.Column("domain", sa.String, nullable=True),
        sa.Column("folder", sa.String, nullable=True),
        sa.Column("flag", sa.String, nullable=False),
        sa.Column("page_type", sa.String, nullable=True),
        sa.Column("visit_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "visited_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("user_id", "url", "flag", name="uq_pages_user_url_flag"),
    )
    op.create_index("ix_pages_user_id", "pages", ["user_id"])
    # Drives the per-(user, flag) recency-ordered cap-trim scan.
    op.create_index(
        "ix_pages_user_flag_visited_at", "pages", ["user_id", "flag", "visited_at"]
    )

    op.create_table(
        "page_sections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "page_id",
            sa.Integer,
            sa.ForeignKey("pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("heading_path", sa.ARRAY(sa.String), nullable=False),
        sa.Column("heading_level", sa.Integer, nullable=True),
        sa.Column("section_index", sa.Integer, nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("date", sa.String, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "page_id", "heading_path", name="uq_page_sections_page_heading"
        ),
    )
    op.create_index("ix_page_sections_page_id", "page_sections", ["page_id"])

    op.create_table(
        "section_embeddings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "section_id",
            sa.Integer,
            sa.ForeignKey("page_sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(DEFAULT_EMBEDDING_DIM), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("section_id", name="uq_section_embeddings_section_id"),
    )

    # HNSW over IVFFlat: no rebuild-on-growth needed, and per-user datasets
    # here are small enough that build cost is a non-issue (pgvector 0.5.0+).
    op.execute(
        "CREATE INDEX idx_section_embeddings_hnsw ON section_embeddings "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_section_embeddings_hnsw")
    op.drop_table("section_embeddings")
    op.drop_index("ix_page_sections_page_id", table_name="page_sections")
    op.drop_table("page_sections")
    op.drop_index("ix_pages_user_flag_visited_at", table_name="pages")
    op.drop_index("ix_pages_user_id", table_name="pages")
    op.drop_table("pages")

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
        sa.Column("heading_path", sa.ARRAY(sa.String), nullable=False),
        sa.Column("heading_level", sa.Integer, nullable=True),
        sa.Column("section_index", sa.Integer, nullable=True),
        sa.Column("page_type", sa.String, nullable=True),
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
            "user_id",
            "url",
            "flag",
            "heading_path",
            name="uq_history_entries_user_url_flag_heading",
        ),
    )
    op.create_index("ix_history_entries_user_id", "history_entries", ["user_id"])
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
    op.execute(
        "CREATE INDEX idx_history_embeddings_hnsw ON history_embeddings "
        "USING hnsw (embedding vector_cosine_ops)"
    )
