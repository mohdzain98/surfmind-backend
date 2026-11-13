"""Data-deletion actions backing the Settings Privacy section.

Both actions key off `sync_account_id`, not the raw browser id, so a
synced user's delete reaches every linked browser's data — matching how
ingestion and retrieval already scope to the shared account. Neither
action touches `sync_accounts`/`users`/`sync_codes`: account existence,
tier, and browser links are preserved, since this is a data reset, not
account deletion.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Page, SearchHistory

# Named ranges for "clear history" — the client sends one of these names,
# never a raw duration, same "name not a number" reasoning as Fast mode's
# strictness presets: a name can be retuned/relabeled without breaking
# whatever the UI happens to have stored. Default is "24h" per product
# decision; an unrecognized/missing name falls back to it rather than
# erroring, consistent with every other optional-enum field in this API.
HISTORY_CLEAR_RANGES: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
HISTORY_CLEAR_DEFAULT_RANGE = "24h"


def resolve_history_clear_range(range_key: Optional[str]) -> str:
    """Resolve a client-sent range name to one of `HISTORY_CLEAR_RANGES`'s
    keys, falling back to the default for anything unrecognized/missing."""
    if range_key in HISTORY_CLEAR_RANGES:
        return range_key
    return HISTORY_CLEAR_DEFAULT_RANGE


async def clear_history(
    sync_account_id: int, db: AsyncSession, since: Optional[datetime] = None
) -> None:
    """Delete history pages/sections/embeddings, optionally scoped to a
    `visited_at >= since` window instead of the whole history.

    Bookmarks and search_history are untouched. `page_sections`/
    `section_embeddings` cascade automatically via `ON DELETE CASCADE`.
    `since=None` clears everything (the pre-existing, still-supported
    full-history-wipe behavior).
    """
    conditions = [Page.user_id == sync_account_id, Page.flag == "history"]
    if since is not None:
        conditions.append(Page.visited_at >= since)
    await db.execute(delete(Page).where(*conditions))
    await db.commit()


async def clear_all_data(sync_account_id: int, db: AsyncSession) -> None:
    """Full wipe: all pages (history + bookmarks), sections, embeddings,
    and search history.

    Categorization doesn't exist in this codebase (reverted) — there's
    nothing to clear or re-seed there yet.
    """
    await db.execute(delete(Page).where(Page.user_id == sync_account_id))
    await db.execute(
        delete(SearchHistory).where(SearchHistory.user_id == sync_account_id)
    )
    await db.commit()
