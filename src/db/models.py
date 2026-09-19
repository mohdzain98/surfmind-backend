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
    # Which linked browser first contributed this page — set on insert
    # only, never overwritten on a later resync, so attribution reflects
    # the original contributor even if a different linked browser
    # revisits the same page. NULL for pre-existing rows from an account
    # that ever had more than one browser (no way to know retroactively).
    source_browser_uuid: Mapped[str | None] = mapped_column(String, nullable=True)
    # Which linked browser most recently synced this page successfully —
    # updated on every insert AND update, unlike source_browser_uuid.
    # Answers "is my data actually synced" (sync_service.get_page_counts),
    # not "who found this first" — a page another linked browser originally
    # contributed still counts as synced for a browser that later re-syncs
    # it, even though source_browser_uuid stays pointed at the original.
    last_synced_browser_uuid: Mapped[str | None] = mapped_column(String, nullable=True)

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
    # Nullable — added after this table already had rows, so existing
    # searches have no recorded timing. Wall-clock elapsed time for /search
    # or the full /search-stream SSE stream, set by core_controller.py.
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AdminUser(Base):
    """An admin operator account — separate from `SyncAccount`/`User`.

    Created only via `scripts/create_admin.py`, never through a public
    endpoint. Backs `/v1/admin/login`.
    """

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AppLog(Base):
    """One WARNING+ log record, written by `src.utility.db_log_handler`.

    Populated automatically from the root logger — every warning/error
    anywhere in the app lands here, including the LLM/embeddings fallback
    and total-failure logging already in `rag.py`/`post_processing.py`/
    `provider.py`. Surfaced read-only via `/v1/admin/status/logs`.
    """

    __tablename__ = "app_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    logger_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class LLMUsage(Base):
    """One LLM call's token usage — written by `core_service/main.py`
    after `safe_invoke_llm_response`/`post_process` return.

    `sync_account_id` has no FK-enforced cascade on delete (`SET NULL`) —
    usage stats are a historical record, not user data, so they should
    outlive the account that generated them.
    """

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    use_case: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sync_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("sync_accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
