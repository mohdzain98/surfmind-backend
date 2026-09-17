"""ORM models for persisted history entries and their embeddings.

Defines the Postgres-backed schema that replaces per-request in-memory
FAISS: `history_entries` holds the ingested page data, `history_embeddings`
holds the pgvector column queried by `HybridRAGService._run_pgvector`.
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.utility.provider import DEFAULT_EMBEDDING_DIM


class Page(Base):
    """One visited/bookmarked URL — the parent unit for retrieval and cap.

    A page-rich in headings still counts as exactly one row here (and one
    cap slot); its heading sections live in `PageSection`. Unique per
    `(user_id, url_hash, flag)` so revisits upsert in place; `visited_at`
    drives cap eviction, `visit_count` is informational.

    `url_hash` (MD5 of `url`) is what's actually indexed/constrained, not
    `url` itself — Postgres btree index rows cap at ~2704 bytes, and a
    sufficiently long URL (long query strings, tracking params, etc.)
    exceeds that on its own. See ingestion_service._hash.
    """

    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "url_hash", "flag", name="uq_pages_user_urlhash_flag"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("sync_accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    url: Mapped[str] = mapped_column(String, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    domain: Mapped[str | None] = mapped_column(String, nullable=True)
    folder: Mapped[str | None] = mapped_column(String, nullable=True)
    flag: Mapped[str] = mapped_column(String, nullable=False)
    # Coarse heuristic bucket ("structured"/"sectioned"/"flat") from heading
    # richness — see ingestion_service._compute_page_types.
    page_type: Mapped[str | None] = mapped_column(String, nullable=True)
    visit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    visited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sections: Mapped[list["PageSection"]] = relationship(
        back_populates="page", cascade="all, delete-orphan"
    )


class PageSection(Base):
    """One heading-scoped section of a `Page`.

    Field names mirror `HistoryItem` in `src/models/core.py` so ingestion
    can map directly from the request payload. Unique per
    `(page_id, heading_path_hash)` — same btree-row-size reasoning as
    `Page.url_hash`: a long/deeply-nested heading path can exceed the
    indexable size on its own, so the hash is what's constrained.
    """

    __tablename__ = "page_sections"
    __table_args__ = (
        UniqueConstraint(
            "page_id", "heading_path_hash", name="uq_page_sections_page_headinghash"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # e.g. ["Docs", "Installation", "Docker Setup"] — [] for headingless
    # pages/older rows, treating the whole page as a single section.
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    heading_path_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    heading_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    page: Mapped["Page"] = relationship(back_populates="sections")
    embedding: Mapped["SectionEmbedding"] = relationship(
        back_populates="section",
        uselist=False,
        cascade="all, delete-orphan",
    )


class SectionEmbedding(Base):
    """Vector embedding for one `PageSection`, queried via pgvector's `<=>`.

    Stored at ingestion time so `/search` never rebuilds an index per
    request — retrieval is a direct `ORDER BY embedding <=> :query` scan.
    """

    __tablename__ = "section_embeddings"
    __table_args__ = (
        UniqueConstraint("section_id", name="uq_section_embeddings_section_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("page_sections.id", ondelete="CASCADE"), nullable=False
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(DEFAULT_EMBEDDING_DIM), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    section: Mapped["PageSection"] = relationship(back_populates="embedding")


class SyncAccount(Base):
    """A shared identity that one or more browsers can be linked to.

    Solo browsers get an auto-created 1:1 account; pairing repoints a
    second browser's `User` row onto an existing account. `tier` is the
    field Pro status will live on later — no schema change needed then.
    """

    __tablename__ = "sync_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tier: Mapped[str] = mapped_column(String, nullable=False, default="free")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    """Maps one browser's own id to the sync account it currently belongs to.

    `browser_uuid` is exactly what the extension already sends as
    `user_id`/`userId` on every request — this table adds the indirection
    to a shared `sync_account_id` on top of that existing identity.
    """

    __tablename__ = "users"

    browser_uuid: Mapped[str] = mapped_column(String, primary_key=True)
    sync_account_id: Mapped[int] = mapped_column(
        ForeignKey("sync_accounts.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SyncCode(Base):
    """A short-lived, single-use code that pairs a browser to an account.

    Generated by the account already holding data, redeemed by the browser
    joining it; `expires_at`/`used` gate redemption in `sync_service`.
    """

    __tablename__ = "sync_codes"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    sync_account_id: Mapped[int] = mapped_column(
        ForeignKey("sync_accounts.id"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SearchHistory(Base):
    """A snapshot of one completed search — query, answer, and sources.

    Lets the "recent searches" accordion render instantly from stored JSON
    instead of re-retrieving/re-generating. Only successful searches are
    persisted (see `search_history_service`).
    """

    __tablename__ = "search_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("sync_accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    flag: Mapped[str] = mapped_column(String, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Mirrors the `docs` list already returned by /search — same shape, no
    # reshaping needed to render the accordion.
    sources: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
