"""Background page classification, triggered on Settings open (while enabled).

Runs via Celery, not FastAPI BackgroundTasks — classifying potentially
hundreds of pages against several category descriptions is real work that
shouldn't block a request. The task itself is a plain sync Celery
function; it bridges into this codebase's async SQLAlchemy stack via
`asyncio.run`, opening its own session per run (same pattern as
`core_controller._ingest_with_own_session`), rather than introducing a
second, synchronous database layer just for this one task.
"""

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.celery_app import celery_app
from src.db.models import Page, PageSection
from src.db.session import async_session_factory, engine
from src.services.category_service.category import list_categories
from src.services.classification_service.classify import PageClassifier
from src.services.llm_service.llm_provider import LLMProvider
from src.utility.logger import AppLogger

logger = AppLogger.get_logger(__name__)

# Page title/folder/domain plus this many characters of concatenated
# section content — Page itself has no content column (content lives on
# PageSection), and feeding a classifier the full text of a heavily
# sectioned page isn't necessary for a coarse category decision.
_CONTENT_TRUNCATE_CHARS = 2000


async def count_unclassified_pages(sync_account_id: int, db: AsyncSession) -> int:
    """Cheap existence check for the trigger endpoint — avoids queuing a
    Celery task when there's genuinely nothing to do."""
    result = await db.execute(
        select(func.count())
        .select_from(Page)
        .where(Page.user_id == sync_account_id, Page.category_id.is_(None))
    )
    return result.scalar_one()


async def _get_classification_targets(
    sync_account_id: int, reclassify_all: bool, db: AsyncSession
) -> list[dict]:
    query = (
        select(
            Page.id,
            Page.title,
            Page.domain,
            Page.folder,
            func.string_agg(PageSection.content, " ").label("content"),
        )
        .join(PageSection, PageSection.page_id == Page.id)
        .where(Page.user_id == sync_account_id)
        .group_by(Page.id)
    )
    if not reclassify_all:
        query = query.where(Page.category_id.is_(None))

    result = await db.execute(query)
    targets = []
    for row in result:
        parts = [
            row.title,
            row.domain,
            row.folder,
            (row.content or "")[:_CONTENT_TRUNCATE_CHARS],
        ]
        targets.append({"page_id": row.id, "content": "\n".join(p for p in parts if p)})
    return targets


async def classify_pages_async(user_id: str, reclassify_all: bool = False) -> dict:
    sync_account_id = int(user_id)
    async with async_session_factory() as db:
        categories = await list_categories(sync_account_id, db)
        if not categories:
            return {"classified": 0, "total": 0}

        targets = await _get_classification_targets(sync_account_id, reclassify_all, db)
        if not targets:
            return {"classified": 0, "total": 0}

        classifier = PageClassifier(llm_provider=LLMProvider())
        valid_names = {cat["name"] for cat in categories}
        name_to_id = {cat["name"]: cat["id"] for cat in categories}

        # One page's total classification failure (both Jev and the Gemini
        # fallback down — rare, but real: seen when a transient network
        # blip hits both calls) must not sink every other page's already-
        # successful result in the same batch, since the commit happens
        # once at the end.
        classified = 0
        for target in targets:
            try:
                result = await classifier.classify(target["content"], categories)
            except Exception as exc:
                logger.warning(
                    "Classification failed for page %s, leaving uncategorized: %s",
                    target["page_id"],
                    exc,
                )
                continue

            logger.info(
                "Classified page %s via %s: %s",
                target["page_id"],
                result["provider"],
                result["category_name"],
            )
            if result["category_name"] not in valid_names:
                continue
            await db.execute(
                Page.__table__.update()
                .where(Page.id == target["page_id"])
                .values(
                    category_id=name_to_id[result["category_name"]],
                    category_confidence=result["confidence"],
                )
            )
            classified += 1

        await db.commit()
        return {"classified": classified, "total": len(targets)}


async def _run_and_dispose(user_id: str, reclassify_all: bool) -> dict:
    """Run one classification pass, then dispose the shared engine's
    connection pool before this event loop closes.

    `asyncio.run` gives each task invocation a brand-new event loop, but
    `engine` (src.db.session) is a module-level singleton whose pooled
    connections are bound to whichever loop created them — reusing a
    pooled connection from a previous (now-closed) loop raises "attached
    to a different loop". Disposing here forces the next invocation to
    open fresh connections against its own new loop instead.
    """
    try:
        return await classify_pages_async(user_id, reclassify_all=reclassify_all)
    finally:
        await engine.dispose()


@celery_app.task(name="classify_pages_task")
def classify_pages_task(user_id: str, reclassify_all: bool = False) -> dict:
    return asyncio.run(_run_and_dispose(user_id, reclassify_all))
