"""Ingestion path that upserts pages, their sections, and embeddings.

Called from `/save-data` so embeddings are written once at ingestion time
instead of being rebuilt from FAISS on every `/search` request. The parent
unit is a `Page` (one row per visited URL); each heading-scoped section of
that page is a child `PageSection`. A single `/save-data` batch can carry
several sections for one URL, but they all fold onto one `Page` row — so a
24-section page consumes exactly one retention-cap slot, not 24. Handles
upsert-by-page-then-sections, embedding only new/changed sections,
tier-gated section summarization for embedding input, and trimming each
user's history to a fixed cap of *pages*.
"""

import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from langchain_core.output_parsers import StrOutputParser
from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Page, PageSection, SectionEmbedding, SyncAccount
from src.models.ai_models import Models
from src.models.core import HistoryItem
from src.services.llm_service.llm_provider import LLMProvider
from src.services.llm_service.prompt_builder import Prompts
from src.utility.logger import AppLogger
from src.utility.provider import EmbeddingsProvider
from src.utility.settings import settings

logger = AppLogger.get_logger(__name__)


def _cap_for(flag: str) -> int:
    """Return the dev/prod-tiered page retention cap for a flag (config/params.yml)."""
    return settings.bookmark_cap if flag == "bookmark" else settings.history_cap


def _default_heading_path(item: HistoryItem, flag: str) -> List[str]:
    """Return the item's heading path, defaulting to a stable per-flag fallback.

    A genuine `heading_path` from the client always wins — this is what
    lets a live-tab-extracted bookmark carry several real, heading-scoped
    sections for one URL, the same way history already does. Only the
    *fallback* (when the client sends none, e.g. a bookmark added without
    an open tab) differs by flag: history falls back to `[title]`, but
    bookmarks fall back to a constant `[]`, never the title. Deriving a
    bookmark's fallback from its tab title caused real accumulation bugs —
    titles drift (notification badges, live page state), and each drift
    missed the `(page_id, heading_path_hash)` upsert conflict target,
    inserting a new orphaned `page_sections` row instead of updating the
    existing one.
    """
    if item.heading_path is not None:
        return item.heading_path
    if flag == "bookmark":
        return []
    return [item.title] if item.title else []


def _hash_url(url: str) -> str:
    """MD5 hex digest of a URL — see `Page.url_hash` for why this is indexed
    instead of the raw URL."""
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def _hash_heading_path(heading_path: List[str]) -> str:
    """MD5 hex digest of a heading path, joined on a rare separator so
    e.g. `['a,b']` and `['a', 'b']` never collide."""
    joined = "\x1e".join(heading_path)
    return hashlib.md5(joined.encode("utf-8")).hexdigest()


def _parse_bookmark_visited_at(date_value: str | int | None) -> datetime:
    """Parse Chrome's `dateAdded` (epoch ms, sent as `date`) into a UTC datetime.

    Falls back to now() if missing/unparseable so the NOT NULL column still
    gets a valid value — this only affects a fresh insert with bad data,
    never overwrites an existing row's `visited_at`.
    """
    if date_value is None:
        return datetime.now(timezone.utc)
    try:
        epoch_ms = float(date_value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)


def _group_by_url(items: List[HistoryItem]) -> Dict[str, List[HistoryItem]]:
    """Group a batch's items by URL — each group becomes one `Page`."""
    groups: Dict[str, List[HistoryItem]] = defaultdict(list)
    for item in items:
        groups[item.url].append(item)
    return groups


def _dedupe_sections(items: List[HistoryItem], flag: str) -> List[HistoryItem]:
    """Keep the last occurrence of each `heading_path` within one URL's items.

    A batch can list the same section multiple times; Postgres's
    `ON CONFLICT DO UPDATE` errors (`CardinalityViolationError`) if one
    statement's VALUES list would update the same conflict target twice.
    """
    by_heading: Dict[Tuple[str, ...], HistoryItem] = {}
    for item in items:
        by_heading[tuple(_default_heading_path(item, flag))] = item
    return list(by_heading.values())


def _classify_page_type(section_count: int, max_heading_level: int) -> str:
    """Bucket a page's structural richness from heading data — no LLM call.

    Real article/docs/product/forum classification needs content signals
    beyond heading structure; this is the coarse, free heuristic the doc
    calls sufficient for now.
    """
    if section_count >= 3 and max_heading_level >= 2:
        return "structured"
    if section_count > 1:
        return "sectioned"
    return "flat"


def _embedding_input(heading_path: List[str], text: str) -> str:
    """Prefix `text` with its heading breadcrumb for a denser embedding signal."""
    if heading_path:
        return " > ".join(heading_path) + "\n" + text
    return text


def _bookmark_embedding_text(
    title: str | None, folder: str | None, domain: str | None
) -> str:
    """Compose a denser embedding input for bookmarks from title/folder/domain.

    Bookmark `content` today is just the title — no real page-text
    extraction yet — so embedding `content` alone caps retrieval quality at
    "however descriptive the title happens to be." Folding in folder/domain
    gives embeddings more to match against, at no extraction cost. Blank
    fields are dropped rather than interpolated, since `folder`/`domain`
    are optional and `None` would otherwise appear as a literal string.
    Takes raw fields (not a `HistoryItem`) so the one-off backfill script
    re-embedding already-stored bookmarks can reuse it without fabricating
    a fake item.
    """
    parts = [title, folder, domain]
    return "\n".join(p for p in parts if p)


async def _get_account_tier(user_id: str, db: AsyncSession) -> str:
    """Look up this sync account's tier; defaults to `"free"` if unresolvable."""
    try:
        account_id = int(user_id)
    except (TypeError, ValueError):
        return "free"
    result = await db.execute(
        select(SyncAccount.tier).where(SyncAccount.id == account_id)
    )
    return result.scalar_one_or_none() or "free"


async def _summarize_section(
    heading_path: List[str], content: str, llm_provider: LLMProvider, prompts: Prompts
) -> str:
    """Generate a short section summary for pro-tier embedding input.

    Falls back to the secondary model on failure, and to `content` itself
    (unchanged) if both fail — a summarization hiccup must never hard-fail
    ingestion.
    """
    prompt = prompts.section_summary_prompt()
    inputs = {"heading_path": " > ".join(heading_path), "content": content}
    try:
        chain = prompt | llm_provider.get(Models.default()) | StrOutputParser()
        return await chain.ainvoke(inputs)
    except Exception as exc:
        logger.warning("Primary LLM failed for section summary, falling back: %s", exc)
        try:
            chain = prompt | llm_provider.get(Models.other()) | StrOutputParser()
            return await chain.ainvoke(inputs)
        except Exception:
            logger.warning("Both LLMs failed for section summary; using raw content")
            return content


async def _build_embedding_inputs(
    changed_items: List[HistoryItem], tier: str, flag: str
) -> List[str]:
    """Return the embedding input text for each changed item, tier-gated.

    Bookmarks: a live-tab-extracted bookmark carries real per-section
    `content` (same shape as history), which embeds normally via
    `heading_path + content`. A bookmark synced without an open tab still
    arrives with `content` equal to its own `title` (no real extraction
    happened) — that weak signal falls back to the composed
    title/folder/domain input instead, skipping the LLM-summary path
    entirely since there's nothing worth summarizing. Free-tier history
    never calls an LLM: embeds `heading_path + content` directly. Pro-tier
    history gets an LLM-generated section summary embedded in its place.
    """
    if flag == "bookmark":
        return [
            (
                _embedding_input(_default_heading_path(item, flag), item.content)
                if item.content and item.content != item.title
                else _bookmark_embedding_text(item.title, item.folder, item.domain)
            )
            for item in changed_items
        ]

    if tier != "pro":
        return [
            _embedding_input(_default_heading_path(item, flag), item.content)
            for item in changed_items
        ]

    llm_provider = LLMProvider()
    prompts = Prompts()
    inputs = []
    for item in changed_items:
        heading_path = _default_heading_path(item, flag)
        summary = await _summarize_section(
            heading_path, item.content, llm_provider, prompts
        )
        inputs.append(_embedding_input(heading_path, summary))
    return inputs


async def _upsert_pages(
    url_groups: Dict[str, List[HistoryItem]], user_id: str, flag: str, db: AsyncSession
) -> Dict[str, int]:
    """Upsert one `Page` row per URL in this batch. Returns `{url: page_id}`.

    History: `visited_at`/`visit_count` bump unconditionally on every sync —
    a history item being in the batch does mean a real visit occurred.

    Bookmarks: a bookmark isn't "visited" every time it re-syncs, so
    `visited_at` is sourced from Chrome's `dateAdded` (payload `date`, epoch
    ms) instead of sync time, and `visited_at`/`visit_count` only change
    when the incoming date genuinely differs from what's stored — i.e. the
    bookmark was removed and re-added in Chrome, giving it a new
    `dateAdded`. An unchanged bookmark re-synced repeatedly leaves both
    untouched, keeping cap eviction meaningfully LRU instead of clustering
    every bookmark at "last synced."
    """
    is_bookmark = flag == "bookmark"
    page_values = []
    for url, sections in url_groups.items():
        max_level = max((s.heading_level or 0) for s in sections)
        entry = {
            "user_id": int(user_id),
            "url": url,
            "url_hash": _hash_url(url),
            "title": sections[-1].title,
            "domain": sections[-1].domain,
            "folder": sections[-1].folder,
            "flag": flag,
            "page_type": _classify_page_type(len(sections), max_level),
        }
        if is_bookmark:
            entry["visited_at"] = _parse_bookmark_visited_at(sections[-1].date)
        page_values.append(entry)

    stmt = pg_insert(Page).values(page_values)
    if is_bookmark:
        date_changed = Page.__table__.c.visited_at != stmt.excluded.visited_at
        set_ = {
            "title": stmt.excluded.title,
            "domain": stmt.excluded.domain,
            "folder": stmt.excluded.folder,
            "page_type": stmt.excluded.page_type,
            "visited_at": case(
                (date_changed, stmt.excluded.visited_at),
                else_=Page.__table__.c.visited_at,
            ),
            "visit_count": case(
                (date_changed, Page.__table__.c.visit_count + 1),
                else_=Page.__table__.c.visit_count,
            ),
        }
    else:
        set_ = {
            "title": stmt.excluded.title,
            "domain": stmt.excluded.domain,
            "folder": stmt.excluded.folder,
            "page_type": stmt.excluded.page_type,
            "visited_at": func.now(),
            "visit_count": Page.__table__.c.visit_count + 1,
        }
    stmt = stmt.on_conflict_do_update(
        constraint="uq_pages_user_urlhash_flag", set_=set_
    ).returning(Page.id, Page.url)
    result = await db.execute(stmt)
    return {row.url: row.id for row in result}


async def ingest_batch(
    items: List[HistoryItem], user_id: str, flag: str, db: AsyncSession
) -> None:
    """Upsert a batch's pages and sections, embed what changed, and trim.

    Each URL in the batch folds onto one `Page` row regardless of how many
    sections it has; sections upsert under `(page_id, heading_path)`. Only
    new/changed sections are re-embedded. Runs cap eviction (by page count)
    in the same transaction, so upsert + trim + the FK-cascaded section/
    embedding cleanup all commit together.
    """
    if not items:
        return

    url_groups = {
        url: _dedupe_sections(sections, flag)
        for url, sections in _group_by_url(items).items()
    }
    all_items = [item for sections in url_groups.values() for item in sections]

    page_id_by_url = await _upsert_pages(url_groups, user_id, flag, db)

    section_keys = [
        (page_id_by_url[item.url], tuple(_default_heading_path(item, flag)))
        for item in all_items
    ]
    page_ids = list(page_id_by_url.values())
    existing = await db.execute(
        select(
            PageSection.page_id, PageSection.heading_path, PageSection.content
        ).where(PageSection.page_id.in_(page_ids))
    )
    existing_content_by_key = {
        (row.page_id, tuple(row.heading_path or [])): row.content for row in existing
    }

    changed_items = [
        item
        for item, key in zip(all_items, section_keys)
        if existing_content_by_key.get(key) != item.content
    ]

    stmt = pg_insert(PageSection).values(
        [
            {
                "page_id": page_id_by_url[item.url],
                "heading_path": _default_heading_path(item, flag),
                "heading_path_hash": _hash_heading_path(
                    _default_heading_path(item, flag)
                ),
                "heading_level": item.heading_level,
                "section_index": item.section_index,
                "content": item.content,
                "date": str(item.date) if item.date is not None else None,
            }
            for item in all_items
        ]
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_page_sections_page_headinghash",
        set_={
            "heading_level": stmt.excluded.heading_level,
            "section_index": stmt.excluded.section_index,
            "content": stmt.excluded.content,
            "date": stmt.excluded.date,
        },
    ).returning(PageSection.id, PageSection.page_id, PageSection.heading_path)
    result = await db.execute(stmt)
    section_id_by_key = {
        (row.page_id, tuple(row.heading_path or [])): row.id for row in result
    }

    if changed_items:
        tier = await _get_account_tier(user_id, db)
        embed_inputs = await _build_embedding_inputs(changed_items, tier, flag)
        embeddings = EmbeddingsProvider.get_default_embeddings()
        vectors = await embeddings.aembed_documents(embed_inputs)
        changed_keys = [
            (page_id_by_url[item.url], tuple(_default_heading_path(item, flag)))
            for item in changed_items
        ]
        changed_section_ids = [section_id_by_key[key] for key in changed_keys]
        await db.execute(
            delete(SectionEmbedding).where(
                SectionEmbedding.section_id.in_(changed_section_ids)
            )
        )
        db.add_all(
            SectionEmbedding(section_id=section_id, embedding=vector)
            for section_id, vector in zip(changed_section_ids, vectors)
        )

    await _trim_to_cap(user_id=user_id, flag=flag, db=db)
    await db.commit()

    logger.info(
        "Ingested %d pages (%d sections, %d re-embedded) for user %s",
        len(url_groups),
        len(all_items),
        len(changed_items),
        user_id,
    )


async def _trim_to_cap(user_id: str, flag: str, db: AsyncSession) -> None:
    """Evict this user's oldest-by-`visited_at` pages for `flag` beyond the cap.

    Deleting `Page` rows cascades to their `PageSection`/`SectionEmbedding`
    rows via `ondelete="CASCADE"`, so the vector index stays in sync for
    free. A 24-section page and a 1-section page each consume one cap slot.
    """
    cap = _cap_for(flag)
    overflow = (
        select(Page.id)
        .where(Page.user_id == int(user_id), Page.flag == flag)
        .order_by(Page.visited_at.desc())
        .offset(cap)
    )
    evict_ids = [row[0] for row in (await db.execute(overflow))]
    if evict_ids:
        await db.execute(delete(Page).where(Page.id.in_(evict_ids)))
