"""Category CRUD and the categorization enable/disable toggle.

Everything here is scoped to `sync_account_id` — the resolved account id,
not a raw browser id — matching every other account-scoped feature in
this codebase. The feature is opt-in: a `SyncAccount` that has never
enabled categorization has zero `Category` rows, and every write path
here (except `enable_categorization` itself) assumes the caller has
already checked `is_categorization_enabled`.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Category, Page, SyncAccount
from src.utility.settings import settings

DEFAULT_CATEGORIES = [
    {
        "name": "Work",
        "description": (
            "Professional tools, work docs, job-related research, "
            "workplace communication"
        ),
    },
    {
        "name": "Shopping",
        "description": "Product pages, e-commerce, price comparisons, order tracking",
    },
    {
        "name": "Learning",
        "description": (
            "Tutorials, documentation, courses, technical or academic reading"
        ),
    },
    {
        "name": "Entertainment",
        "description": "Videos, social media, games, news, leisure browsing",
    },
]

# Seeded alongside DEFAULT_CATEGORIES, but tracked separately — it's a
# structural fallback bucket, not one of the user's real category slots.
# Jev's `Choice` primitive (classification_service/classify.py) can't
# return "no match": it's structurally forced to pick one of whatever
# criteria it's given. Giving it this as a literal 5th option lets a page
# that doesn't fit any real category land honestly in "Other" instead of
# being jammed into the real category Jev deems least-bad. Excluded from
# count_categories' cap check (see below) — a free-tier account still
# gets its full 4 real categories, "Other" doesn't eat one of them.
OTHER_CATEGORY_NAME = "Other"
OTHER_CATEGORY = {
    "name": OTHER_CATEGORY_NAME,
    "description": "Doesn't clearly fit any of this account's other categories",
}


async def is_categorization_enabled(sync_account_id: int, db: AsyncSession) -> bool:
    result = await db.execute(
        select(SyncAccount.categorization_enabled).where(
            SyncAccount.id == sync_account_id
        )
    )
    return bool(result.scalar_one_or_none())


async def _create_default_categories(sync_account_id: int, db: AsyncSession) -> None:
    """Idempotent — re-enabling after a disable must not duplicate or error
    on categories that already exist from a prior enable. Seeds "Other"
    alongside the real defaults so it's always available as a
    classification target from the very first enable."""
    stmt = pg_insert(Category).values(
        [
            {
                "user_id": sync_account_id,
                "name": cat["name"],
                "description": cat["description"],
                "is_default": True,
            }
            for cat in [*DEFAULT_CATEGORIES, OTHER_CATEGORY]
        ]
    )
    stmt = stmt.on_conflict_do_nothing(constraint="uq_categories_user_name")
    await db.execute(stmt)


async def enable_categorization(sync_account_id: int, db: AsyncSession) -> bool:
    """Flip the flag on and seed defaults. Returns False if already enabled
    (caller uses this to decide whether to fire an immediate first
    classification pass — no-op on an already-enabled account)."""
    already_enabled = await is_categorization_enabled(sync_account_id, db)
    if already_enabled:
        return False

    await db.execute(
        SyncAccount.__table__.update()
        .where(SyncAccount.id == sync_account_id)
        .values(categorization_enabled=True)
    )
    await _create_default_categories(sync_account_id, db)
    await db.commit()
    return True


async def disable_categorization(sync_account_id: int, db: AsyncSession) -> None:
    """Flip the flag off only — categories and pages.category_id are left
    untouched so re-enabling later picks up where it left off."""
    await db.execute(
        SyncAccount.__table__.update()
        .where(SyncAccount.id == sync_account_id)
        .values(categorization_enabled=False)
    )
    await db.commit()


async def get_refresh_available_at(
    sync_account_id: int, db: AsyncSession
) -> datetime | None:
    """When this account's refresh button becomes available again.

    `None` means it's available right now (never run, or cooldown already
    elapsed) — the frontend can render the button enabled with no timer.
    """
    result = await db.execute(
        select(SyncAccount.last_classified_at).where(SyncAccount.id == sync_account_id)
    )
    last_classified_at = result.scalar_one_or_none()
    if last_classified_at is None:
        return None

    available_at = last_classified_at + timedelta(
        hours=settings.classification_refresh_cooldown_hours
    )
    if available_at <= datetime.now(timezone.utc):
        return None
    return available_at


async def refresh_categorization(
    sync_account_id: int, db: AsyncSession
) -> datetime | None:
    """Stamp `last_classified_at` and bump `refresh_count`, to start a
    fresh cooldown window and track lifetime refresh adoption for admin.

    Caller (the /refresh route) has already confirmed via
    `get_refresh_available_at` that the cooldown has elapsed — this just
    records the attempt, same "stamp at trigger time, not completion time"
    convention as everywhere else a Celery task gets queued from here.
    Returns the next `refresh_available_at` for the response.
    """
    now = datetime.now(timezone.utc)
    await db.execute(
        SyncAccount.__table__.update()
        .where(SyncAccount.id == sync_account_id)
        .values(last_classified_at=now, refresh_count=SyncAccount.refresh_count + 1)
    )
    await db.commit()
    return now + timedelta(hours=settings.classification_refresh_cooldown_hours)


async def list_categories(sync_account_id: int, db: AsyncSession) -> list[dict]:
    """ "Other" is always sorted last — it's the structural fallback bucket,
    not a category the user actively chose, so it shouldn't compete with
    real categories for position in the UI."""
    result = await db.execute(
        select(Category)
        .where(Category.user_id == sync_account_id)
        .order_by(Category.name == OTHER_CATEGORY_NAME, Category.id)
    )
    return [
        {
            "id": cat.id,
            "name": cat.name,
            "description": cat.description,
            "is_default": cat.is_default,
            "deletable": cat.name != OTHER_CATEGORY_NAME,
        }
        for cat in result.scalars()
    ]


async def get_category_usage(sync_account_id: int, db: AsyncSession) -> list[dict]:
    """This account's categories with how many pages are actually filed
    under each — the admin-facing "what categories is this user using"
    view (list_categories alone has no page counts). Outer-joined so an
    unused category still shows up with page_count 0 rather than being
    silently omitted.
    """
    result = await db.execute(
        select(
            Category.id,
            Category.name,
            Category.is_default,
            func.count(Page.id).label("page_count"),
        )
        .outerjoin(
            Page,
            (Page.category_id == Category.id) & (Page.user_id == sync_account_id),
        )
        .where(Category.user_id == sync_account_id)
        .group_by(Category.id, Category.name, Category.is_default)
        .order_by(Category.name == OTHER_CATEGORY_NAME, Category.id)
    )
    return [
        {
            "id": row.id,
            "name": row.name,
            "is_default": row.is_default,
            "page_count": row.page_count,
        }
        for row in result
    ]


async def count_categories(sync_account_id: int, db: AsyncSession) -> int:
    """Count this account's categories toward its tier's cap.

    Excludes "Other" — it's a structural fallback bucket seeded for
    every account, not one of the account's real category slots, so it
    must not eat into a free-tier account's 4-category allowance.
    """
    result = await db.execute(
        select(func.count())
        .select_from(Category)
        .where(
            Category.user_id == sync_account_id,
            Category.name != OTHER_CATEGORY_NAME,
        )
    )
    return result.scalar_one()


async def create_category(
    sync_account_id: int, name: str, description: str, tier: str, db: AsyncSession
) -> Category:
    """Raises ValueError if the account is over its tier's category cap."""
    count = await count_categories(sync_account_id, db)
    if count >= settings.category_limit(tier):
        raise ValueError("Category limit reached for your plan")

    category = Category(
        user_id=sync_account_id, name=name, description=description, is_default=False
    )
    db.add(category)
    await db.commit()
    return category


async def delete_category(
    category_id: int, sync_account_id: int, db: AsyncSession
) -> None:
    """No special-casing for `is_default` — defaults are deletable too.
    `pages.category_id`'s `ON DELETE SET NULL` uncategorizes affected pages
    automatically; nothing else to clean up here.

    "Other" is the one exception — it's a structural fallback bucket
    Jev needs to always have available (see OTHER_CATEGORY above), not a
    real user category, so deleting it is rejected here regardless of
    what the frontend does. Raises ValueError, same as create_category's
    cap check, for the route to turn into a 400.
    """
    result = await db.execute(
        select(Category.name).where(
            Category.id == category_id, Category.user_id == sync_account_id
        )
    )
    name = result.scalar_one_or_none()
    if name is None:
        return
    if name == OTHER_CATEGORY_NAME:
        raise ValueError('The "Other" category cannot be deleted')

    await db.execute(
        delete(Category).where(
            Category.id == category_id, Category.user_id == sync_account_id
        )
    )
    await db.commit()


async def update_category_description(
    category_id: int, sync_account_id: int, description: str, db: AsyncSession
) -> Category:
    """Edit a category's description — the only field edit covers. `name`
    is never editable: it's the account-unique identity classification
    actually matches against (`classify_pages_async`'s `name_to_id`), not
    just a label, so changing it would silently detach it from whatever
    Jev was told last run. Works for default categories too (Work,
    Shopping, etc.) — only "Other" is excluded, same as delete, since its
    description is tied to its structural fallback meaning.

    Raises ValueError (404-equivalent, no such category on this account)
    or (for "Other") the same not-editable error delete_category raises.
    """
    result = await db.execute(
        select(Category).where(
            Category.id == category_id, Category.user_id == sync_account_id
        )
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise ValueError("Category not found")
    if category.name == OTHER_CATEGORY_NAME:
        raise ValueError('The "Other" category cannot be edited')

    category.description = description
    await db.commit()
    return category


async def list_categorized_pages(sync_account_id: int, db: AsyncSession) -> dict:
    """Every history page for this account, grouped by category — the
    UI's "here are all the pages classified as Work" view. Pages with no
    category yet (never classified, or uncategorized by a category
    delete) come back under `uncategorized`, not silently dropped.

    History only, for now (see classification_service.tasks) — bookmarks
    are excluded rather than listed as permanently "uncategorized," which
    would be confusing noise since they're never actually eligible.
    """
    categories = await list_categories(sync_account_id, db)
    by_id = {cat["id"]: {**cat, "pages": []} for cat in categories}
    uncategorized: list[dict] = []

    result = await db.execute(
        select(
            Page.id,
            Page.url,
            Page.title,
            Page.domain,
            Page.folder,
            Page.flag,
            Page.category_id,
            Page.category_confidence,
            Page.visited_at,
        ).where(Page.user_id == sync_account_id, Page.flag == "history")
    )
    for row in result:
        page = {
            "id": row.id,
            "url": row.url,
            "title": row.title,
            "domain": row.domain,
            "folder": row.folder,
            "flag": row.flag,
            "category_confidence": row.category_confidence,
            "visited_at": row.visited_at.isoformat() if row.visited_at else None,
        }
        if row.category_id in by_id:
            by_id[row.category_id]["pages"].append(page)
        else:
            uncategorized.append(page)

    return {"categories": list(by_id.values()), "uncategorized": uncategorized}


async def get_search_category_analytics(
    sync_account_id: int, db: AsyncSession
) -> list[dict]:
    """How many past searches' matched sources fall into each category —
    "what is this user searching more". Cross-references each stored
    search's `sources` (the same `docs` shape /search already returns)
    against `pages.category_id` by matching URL hash, the same way
    `Page.url_hash` is already indexed instead of the raw URL elsewhere.

    A source URL with no matching `pages` row (e.g. since evicted by the
    retention cap) simply isn't counted — this is a best-effort signal,
    not an audit trail. Joined to history pages only, for now (see
    classification_service.tasks) — a bookmark hit would otherwise always
    fall into "Uncategorized" since it's never actually eligible, diluting
    the signal this is meant to give.
    """
    result = await db.execute(
        text("""
            SELECT c.id AS category_id,
                   COALESCE(c.name, 'Uncategorized') AS category_name,
                   COUNT(*) AS search_count
            FROM search_history sh
            CROSS JOIN LATERAL jsonb_array_elements(sh.sources) AS source_elem
            JOIN pages p
                ON p.user_id = sh.user_id
                AND p.url_hash = md5(source_elem->'metadata'->>'source')
                AND p.flag = 'history'
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE sh.user_id = :user_id AND sh.sources IS NOT NULL
            GROUP BY c.id, c.name
            ORDER BY search_count DESC
            """),
        {"user_id": sync_account_id},
    )
    return [
        {
            "category_id": row.category_id,
            "category_name": row.category_name,
            "search_count": row.search_count,
        }
        for row in result
    ]
