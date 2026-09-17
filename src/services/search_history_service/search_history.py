"""Persists and reads snapshots of completed searches ("recent searches").

`persist_search` runs as a fire-and-forget background task after a
`/search` or `/search-stream` response has already gone out, so it opens
its own `AsyncSession` rather than reusing the request-scoped one, which
may already be torn down by the time the background task runs.
"""

from typing import Any, Dict, List

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import SearchHistory
from src.db.session import async_session_factory
from src.utility.logger import AppLogger
from src.utility.settings import settings

logger = AppLogger.get_logger(__name__)


async def persist_search(
    user_id: str, query: str, flag: str, answer: str, sources: List[dict]
) -> None:
    """Store a completed search and trim to the configured retention cap.

    Swallows and logs any failure — recent-searches storage is a
    nice-to-have, never worth failing or retrying a search over.
    """
    try:
        async with async_session_factory() as db:
            db.add(
                SearchHistory(
                    user_id=int(user_id),
                    query=query,
                    flag=flag,
                    answer=answer,
                    sources=sources,
                )
            )
            await db.flush()
            await _trim_to_cap(user_id=int(user_id), db=db)
            await db.commit()
    except Exception as exc:
        logger.warning("Failed to persist search history: %s", exc)


async def _trim_to_cap(user_id: int, db: AsyncSession) -> None:
    """Evict this user's oldest-by-`created_at` rows beyond the retention cap."""
    cap = settings.search_history_retention_cap
    overflow = (
        select(SearchHistory.id)
        .where(SearchHistory.user_id == user_id)
        .order_by(SearchHistory.created_at.desc())
        .offset(cap)
    )
    evict_ids = [row[0] for row in (await db.execute(overflow))]
    if evict_ids:
        await db.execute(delete(SearchHistory).where(SearchHistory.id.in_(evict_ids)))


async def get_recent_searches(
    user_id: str, limit: int, db: AsyncSession
) -> List[Dict[str, Any]]:
    """Return this account's most recent searches, newest first."""
    result = await db.execute(
        select(SearchHistory)
        .where(SearchHistory.user_id == int(user_id))
        .order_by(SearchHistory.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": row.id,
            "query": row.query,
            "flag": row.flag,
            "answer": row.answer,
            "sources": row.sources,
            "created_at": row.created_at.isoformat(),
        }
        for row in result.scalars()
    ]
