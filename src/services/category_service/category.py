"""Category CRUD and the categorization enable/disable toggle.

Everything here is scoped to `sync_account_id` — the resolved account id,
not a raw browser id — matching every other account-scoped feature in
this codebase. The feature is opt-in: a `SyncAccount` that has never
enabled categorization has zero `Category` rows, and every write path
here (except `enable_categorization` itself) assumes the caller has
already checked `is_categorization_enabled`.
"""

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Category, SyncAccount
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


async def is_categorization_enabled(sync_account_id: int, db: AsyncSession) -> bool:
    result = await db.execute(
        select(SyncAccount.categorization_enabled).where(
            SyncAccount.id == sync_account_id
        )
    )
    return bool(result.scalar_one_or_none())


async def _create_default_categories(sync_account_id: int, db: AsyncSession) -> None:
    """Idempotent — re-enabling after a disable must not duplicate or error
    on categories that already exist from a prior enable."""
    stmt = pg_insert(Category).values(
        [
            {
                "user_id": sync_account_id,
                "name": cat["name"],
                "description": cat["description"],
                "is_default": True,
            }
            for cat in DEFAULT_CATEGORIES
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


async def list_categories(sync_account_id: int, db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Category).where(Category.user_id == sync_account_id)
    )
    return [
        {
            "id": cat.id,
            "name": cat.name,
            "description": cat.description,
            "is_default": cat.is_default,
        }
        for cat in result.scalars()
    ]


async def count_categories(sync_account_id: int, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Category)
        .where(Category.user_id == sync_account_id)
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
    """
    await db.execute(
        delete(Category).where(
            Category.id == category_id, Category.user_id == sync_account_id
        )
    )
    await db.commit()
