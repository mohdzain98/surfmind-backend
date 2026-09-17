"""Category CRUD, enable/disable toggle, and classification trigger routes.

Delegates all account/category logic to `src.services.category_service`,
and task queuing to `src.services.classification_service.tasks`. Every
endpoint is POST — including what the original plan wrote as GET for
listing/status — since GET requests from an MV3 service worker don't
reliably carry an Origin header, which breaks nginx's Origin-allowlist
check upstream (the same bug already found and fixed on `/v1/sync/status`
and `/v1/recent-searches`).
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.celery_app import celery_app
from src.db.models import SyncAccount
from src.db.session import get_db
from src.models.core import (
    CategoryListRequest,
    CategoryPagesRequest,
    ClassifyRequest,
    ClassifyStatusRequest,
    CreateCategoryRequest,
    DisableCategorizationRequest,
    EnableCategorizationRequest,
    SearchAnalyticsRequest,
)
from src.services.category_service.category import (
    create_category,
    delete_category,
    disable_categorization,
    enable_categorization,
    get_search_category_analytics,
    is_categorization_enabled,
    list_categories,
    list_categorized_pages,
)
from src.services.classification_service.tasks import (
    classify_pages_task,
    count_unclassified_pages,
)
from src.services.sync_service.sync import resolve_sync_account_id
from src.utility.logger import AppLogger

logger = AppLogger.get_logger(__name__)

router = APIRouter(prefix="/v1/categories", tags=["Categories"])


async def _get_tier(sync_account_id: int, db: AsyncSession) -> str:
    result = await db.execute(
        select(SyncAccount.tier).where(SyncAccount.id == sync_account_id)
    )
    return result.scalar_one_or_none() or "free"


@router.post("/list", response_model=Dict[str, Any])
async def list_categories_route(
    payload: CategoryListRequest, db: AsyncSession = Depends(get_db)
):
    """Return this account's enabled status + categories (empty list if
    never enabled — harmless either way, no error)."""
    sync_account_id = await resolve_sync_account_id(
        browser_uuid=payload.browser_uuid, db=db
    )
    enabled = await is_categorization_enabled(sync_account_id, db)
    categories = await list_categories(sync_account_id, db)
    return {"enabled": enabled, "categories": categories}


@router.post("/pages", response_model=Dict[str, Any])
async def list_categorized_pages_route(
    payload: CategoryPagesRequest, db: AsyncSession = Depends(get_db)
):
    """Every page for this account, grouped by category — the UI's "here
    are all the pages classified as Work" view."""
    sync_account_id = await resolve_sync_account_id(
        browser_uuid=payload.browser_uuid, db=db
    )
    return await list_categorized_pages(sync_account_id, db)


@router.post("/search-analytics", response_model=Dict[str, Any])
async def search_analytics_route(
    payload: SearchAnalyticsRequest, db: AsyncSession = Depends(get_db)
):
    """How many past searches' matched sources fall into each category."""
    sync_account_id = await resolve_sync_account_id(
        browser_uuid=payload.browser_uuid, db=db
    )
    by_category = await get_search_category_analytics(sync_account_id, db)
    return {"by_category": by_category}


@router.post("/create", response_model=Dict[str, Any])
async def create_category_route(
    payload: CreateCategoryRequest, db: AsyncSession = Depends(get_db)
):
    """Create a custom category. Checked here (defense in depth), not just
    left to the frontend: disabled accounts and over-cap accounts are
    rejected even on a direct API call."""
    sync_account_id = await resolve_sync_account_id(
        browser_uuid=payload.browser_uuid, db=db
    )
    if not await is_categorization_enabled(sync_account_id, db):
        raise HTTPException(400, "Categorization is not enabled for this account")

    tier = await _get_tier(sync_account_id, db)
    try:
        category = await create_category(
            sync_account_id, payload.name, payload.description, tier, db
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "id": category.id,
        "name": category.name,
        "description": category.description,
    }


@router.delete("/{category_id}", response_model=Dict[str, Any])
async def delete_category_route(
    category_id: int, browser_uuid: str, db: AsyncSession = Depends(get_db)
):
    """Delete a category (default or custom, no special-casing). Affected
    pages are uncategorized automatically via ON DELETE SET NULL, not
    deleted."""
    sync_account_id = await resolve_sync_account_id(browser_uuid=browser_uuid, db=db)
    await delete_category(category_id, sync_account_id, db)
    return {"success": True}


@router.post("/enable", response_model=Dict[str, Any])
async def enable_route(
    payload: EnableCategorizationRequest, db: AsyncSession = Depends(get_db)
):
    """Flip the flag on, seed defaults (idempotent), and fire an immediate
    first classification pass so the user sees results right away."""
    sync_account_id = await resolve_sync_account_id(
        browser_uuid=payload.browser_uuid, db=db
    )
    newly_enabled = await enable_categorization(sync_account_id, db)
    if not newly_enabled:
        return {"status": "already_enabled"}

    task = classify_pages_task.delay(str(sync_account_id))
    return {"status": "enabled", "task_id": task.id}


@router.post("/disable", response_model=Dict[str, Any])
async def disable_route(
    payload: DisableCategorizationRequest, db: AsyncSession = Depends(get_db)
):
    """Flip the flag off only — categories and pages.category_id survive so
    re-enabling later doesn't lose anything."""
    sync_account_id = await resolve_sync_account_id(
        browser_uuid=payload.browser_uuid, db=db
    )
    await disable_categorization(sync_account_id, db)
    return {"status": "disabled"}


@router.post("/classify", response_model=Dict[str, Any])
async def classify_route(payload: ClassifyRequest, db: AsyncSession = Depends(get_db)):
    """Called by the frontend when Settings opens. Silent no-op (not an
    error) if categorization is disabled, so the frontend can call this
    unconditionally without checking the enabled flag itself first."""
    sync_account_id = await resolve_sync_account_id(
        browser_uuid=payload.browser_uuid, db=db
    )
    if not await is_categorization_enabled(sync_account_id, db):
        return {"status": "not_enabled"}

    if not payload.reclassify_all:
        unclassified = await count_unclassified_pages(sync_account_id, db)
        if unclassified == 0:
            return {"status": "nothing_to_classify"}

    task = classify_pages_task.delay(
        str(sync_account_id), reclassify_all=payload.reclassify_all
    )
    return {"task_id": task.id, "status": "queued"}


@router.post("/classify-status", response_model=Dict[str, Any])
async def classify_status_route(payload: ClassifyStatusRequest):
    result = celery_app.AsyncResult(payload.task_id)
    return {"status": result.status, "ready": result.ready()}
