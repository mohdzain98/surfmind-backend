"""Data-deletion actions backing the Settings Privacy section.

Both actions key off `sync_account_id`, not the raw browser id, so a
synced user's delete reaches every linked browser's data — matching how
ingestion and retrieval already scope to the shared account. Neither
action touches `sync_accounts`/`users`/`sync_codes`: account existence,
tier, and browser links are preserved, since this is a data reset, not
account deletion.
"""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Page, SearchHistory


async def clear_history(sync_account_id: int, db: AsyncSession) -> None:
    """Delete history pages/sections/embeddings only.

    Bookmarks and search_history are untouched. `page_sections`/
    `section_embeddings` cascade automatically via `ON DELETE CASCADE`.
    """
    await db.execute(
        delete(Page).where(Page.user_id == sync_account_id, Page.flag == "history")
    )
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
