"""Admin routes: login, and read-only server/data status.

Login issues a JWT (`admin_service.create_token`); every route below it is
gated by `get_current_admin`, which requires a valid `Authorization: Bearer
<token>` header. Admin accounts are provisioned only via
`scripts/create_admin.py` — there's no public registration endpoint.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.controller.core_controller import redis_client
from src.db.models import (
    AppLog,
    LLMUsage,
    Page,
    SearchHistory,
    SyncAccount,
    SyncCode,
    User,
)
from src.db.session import get_db
from src.models.core import (
    AdminClearDataRequest,
    AdminLoginRequest,
    AdminUnlinkBrowserRequest,
)
from src.services.admin_service.admin import (
    InvalidAdminToken,
    create_token,
    decode_token,
    verify_admin,
)
from src.services.privacy_service.privacy import clear_all_data, clear_history
from src.services.sync_service.sync import unlink
from src.utility.logger import AppLogger

# How long a captured log row is kept — trimmed lazily on read (this repo
# has no scheduler; see sync_service._delete_expired_codes for the same
# clean-up-on-next-relevant-call pattern), not via a cron job.
LOG_RETENTION = timedelta(days=30)

logger = AppLogger.get_logger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["Admin"])

_bearer_scheme = HTTPBearer()


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict:
    """FastAPI dependency gating every admin route below `/login`."""
    try:
        return decode_token(credentials.credentials)
    except InvalidAdminToken:
        raise HTTPException(status_code=401, detail="Invalid or expired admin token")


@router.post("/login")
async def login_route(payload: AdminLoginRequest, db: AsyncSession = Depends(get_db)):
    """Verify admin credentials and issue a bearer token."""
    admin = await verify_admin(payload.username, payload.password, db)
    if admin is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token, expires_at = create_token(admin.id, admin.username)
    return {"success": True, "token": token, "expiresAt": expires_at.isoformat()}


@router.get("/status/health")
async def health_route(
    db: AsyncSession = Depends(get_db), _admin: dict = Depends(get_current_admin)
):
    """On-demand dependency health check — Postgres, pgvector, Redis.

    Mirrors the startup check in `main_controller.py`'s `lifespan()`, but
    callable anytime instead of only at boot. Each dependency is checked
    independently so one being down doesn't hide the other's status.
    """
    postgres = {"ok": False, "detail": None}
    try:
        await db.execute(text("SELECT 1"))
        postgres["ok"] = True
    except Exception as exc:
        postgres["detail"] = str(exc)

    pgvector = {"ok": False, "detail": None}
    try:
        result = await db.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        )
        pgvector["ok"] = result.scalar_one_or_none() is not None
        if not pgvector["ok"]:
            pgvector["detail"] = "vector extension not installed"
    except Exception as exc:
        pgvector["detail"] = str(exc)

    redis_status = {"ok": False, "detail": None}
    try:
        await asyncio.to_thread(redis_client.ping)
        redis_status["ok"] = True
        info = await asyncio.to_thread(redis_client.info, "memory")
        redis_status["usedMemoryHuman"] = info.get("used_memory_human")
        redis_status["connectedClients"] = (
            await asyncio.to_thread(redis_client.info, "clients")
        ).get("connected_clients")
        redis_status["keyCount"] = await asyncio.to_thread(redis_client.dbsize)
    except Exception as exc:
        redis_status["detail"] = str(exc)

    return {"postgres": postgres, "pgvector": pgvector, "redis": redis_status}


@router.get("/status/stats")
async def stats_route(
    db: AsyncSession = Depends(get_db), _admin: dict = Depends(get_current_admin)
):
    """Basic usage counts: accounts, linked vs. solo, pages by flag."""
    total_accounts = (
        await db.execute(select(func.count()).select_from(SyncAccount))
    ).scalar_one()

    linked_accounts_result = await db.execute(
        select(func.count()).select_from(
            select(User.sync_account_id)
            .group_by(User.sync_account_id)
            .having(func.count() > 1)
            .subquery()
        )
    )
    linked_accounts = linked_accounts_result.scalar_one()

    page_counts_result = await db.execute(
        select(Page.flag, func.count()).group_by(Page.flag)
    )
    page_counts = {flag: count for flag, count in page_counts_result.all()}

    return {
        "total_accounts": total_accounts,
        "linked_accounts": linked_accounts,
        "total_pages_history": page_counts.get("history", 0),
        "total_pages_bookmark": page_counts.get("bookmark", 0),
    }


@router.get("/status/logs")
async def logs_route(
    level: Optional[str] = Query(default=None),
    logger_name: Optional[str] = Query(default=None),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """Paginated, newest-first WARNING+ log records.

    Populated automatically by `src.utility.db_log_handler` from the root
    logger — this includes the existing LLM/embeddings fallback and
    total-failure logging in `rag.py`/`post_processing.py`/`provider.py`,
    with no separate instrumentation needed. Filter by `logger_name` (e.g.
    `rag`, `post_processing`, `provider`) to see just those, or by
    `since`/`until` (ISO 8601, e.g. `2026-09-01T00:00:00Z`) to bound the
    date range — both optional and independent (either, both, or neither).
    """
    cutoff = datetime.now(timezone.utc) - LOG_RETENTION
    await db.execute(delete(AppLog).where(AppLog.created_at < cutoff))
    await db.commit()

    query = select(AppLog).order_by(AppLog.created_at.desc())
    if level:
        query = query.where(AppLog.level == level.upper())
    if logger_name:
        query = query.where(AppLog.logger_name.ilike(f"%{logger_name}%"))
    if since:
        query = query.where(AppLog.created_at >= since)
    if until:
        query = query.where(AppLog.created_at <= until)
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    rows = result.scalars().all()

    return {
        "logs": [
            {
                "id": row.id,
                "level": row.level,
                "loggerName": row.logger_name,
                "message": row.message,
                "extra": row.extra,
                "createdAt": row.created_at.isoformat(),
            }
            for row in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/status/llm-usage")
async def llm_usage_route(
    since_days: int = Query(default=7, ge=1, le=365),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """Aggregated token usage grouped by (use_case, provider, model).

    Populated by `core_service/main.py::_record_llm_usage` after each
    `safe_invoke_llm_response`/`post_process` call — see `LLMUsage`. Date
    range: pass explicit `since`/`until` (ISO 8601) for a bounded window,
    or just `since_days` (default 7) to mean "the last N days from now" —
    `since`/`until` take precedence over `since_days` when given. Grouped
    rows are naturally few (one per use_case/provider/model combo), but
    `limit`/`offset` are included for consistency with the other list
    routes.
    """
    query = select(
        LLMUsage.use_case,
        LLMUsage.provider,
        LLMUsage.model,
        func.sum(LLMUsage.input_tokens).label("input_tokens"),
        func.sum(LLMUsage.output_tokens).label("output_tokens"),
        func.count().label("calls"),
    )
    if since:
        query = query.where(LLMUsage.created_at >= since)
    elif since_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        query = query.where(LLMUsage.created_at >= cutoff)
    if until:
        query = query.where(LLMUsage.created_at <= until)
    query = (
        query.group_by(LLMUsage.use_case, LLMUsage.provider, LLMUsage.model)
        .order_by(LLMUsage.use_case)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)

    return {
        "usage": [
            {
                "useCase": row.use_case,
                "provider": row.provider,
                "model": row.model,
                "inputTokens": row.input_tokens,
                "outputTokens": row.output_tokens,
                "calls": row.calls,
            }
            for row in result.all()
        ]
    }


@router.get("/status/search-metrics")
async def search_metrics_route(
    since_days: int = Query(default=7, ge=1, le=365),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """Search volume + latency, grouped by flag.

    `SearchHistory` (populated by `search_history_service.persist_search`
    after every successful `/search`/`/search-stream` call) already records
    volume; `duration_ms` (added alongside this route) gives latency.
    Existing rows predating this column have `duration_ms = NULL` and are
    excluded from the avg/max, not counted as zero. Date range: explicit
    `since`/`until` (ISO 8601) takes precedence over `since_days` (default
    7 = last N days from now), same as `/status/llm-usage`.
    """
    query = select(
        SearchHistory.flag,
        func.count().label("total"),
        func.avg(SearchHistory.duration_ms).label("avg_duration_ms"),
        func.max(SearchHistory.duration_ms).label("max_duration_ms"),
    )
    if since:
        query = query.where(SearchHistory.created_at >= since)
    elif since_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        query = query.where(SearchHistory.created_at >= cutoff)
    if until:
        query = query.where(SearchHistory.created_at <= until)
    query = (
        query.group_by(SearchHistory.flag)
        .order_by(SearchHistory.flag)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)

    return {
        "metrics": [
            {
                "flag": row.flag,
                "totalSearches": row.total,
                "avgDurationMs": (
                    round(row.avg_duration_ms) if row.avg_duration_ms else None
                ),
                "maxDurationMs": row.max_duration_ms,
            }
            for row in result.all()
        ]
    }


@router.get("/accounts/{sync_account_id}")
async def account_detail_route(
    sync_account_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """One account's full picture: browsers, pages, LLM usage, searches."""
    account = await db.get(SyncAccount, sync_account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    browsers_result = await db.execute(
        select(User.browser_uuid).where(User.sync_account_id == sync_account_id)
    )
    browsers = [row[0] for row in browsers_result.all()]

    page_counts_result = await db.execute(
        select(Page.flag, func.count())
        .where(Page.user_id == sync_account_id)
        .group_by(Page.flag)
    )
    page_counts = {flag: count for flag, count in page_counts_result.all()}

    usage_result = await db.execute(
        select(
            func.coalesce(func.sum(LLMUsage.input_tokens), 0),
            func.coalesce(func.sum(LLMUsage.output_tokens), 0),
        ).where(LLMUsage.sync_account_id == sync_account_id)
    )
    input_tokens, output_tokens = usage_result.one()

    search_count = (
        await db.execute(
            select(func.count())
            .select_from(SearchHistory)
            .where(SearchHistory.user_id == sync_account_id)
        )
    ).scalar_one()

    return {
        "syncAccountId": sync_account_id,
        "tier": account.tier,
        "browserCount": len(browsers),
        "browsers": browsers,
        "isLinked": len(browsers) > 1,
        "pagesHistory": page_counts.get("history", 0),
        "pagesBookmark": page_counts.get("bookmark", 0),
        "llmInputTokens": input_tokens,
        "llmOutputTokens": output_tokens,
        "searchCount": search_count,
    }


@router.post("/accounts/{sync_account_id}/unlink-browser")
async def admin_unlink_browser_route(
    sync_account_id: int,
    payload: AdminUnlinkBrowserRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Force-detach one browser from an account onto its own fresh account.

    Delegates to the same `sync_service.unlink` a browser uses on itself —
    reclaims that browser's own contributed pages per its existing logic.
    `sync_account_id` in the path is informational/for the audit log only;
    `unlink` resolves the browser's actual current account itself.
    """
    new_account_id = await unlink(browser_uuid=payload.browser_uuid, db=db)
    logger.warning(
        "Admin action: unlink-browser",
        extra={
            "admin": admin.get("username"),
            "from_account": sync_account_id,
            "browser_uuid": payload.browser_uuid,
            "new_account": new_account_id,
        },
    )
    return {"success": True, "newSyncAccountId": new_account_id}


@router.post("/accounts/{sync_account_id}/clear-data")
async def admin_clear_data_route(
    sync_account_id: int,
    payload: AdminClearDataRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Wipe an account's data — `scope="history"` or `scope="all"`."""
    if payload.scope not in ("history", "all"):
        raise HTTPException(status_code=400, detail="scope must be 'history' or 'all'")
    if payload.scope == "history":
        await clear_history(sync_account_id, db)
    else:
        await clear_all_data(sync_account_id, db)
    logger.warning(
        "Admin action: clear-data",
        extra={
            "admin": admin.get("username"),
            "sync_account_id": sync_account_id,
            "scope": payload.scope,
        },
    )
    return {"success": True, "syncAccountId": sync_account_id, "scope": payload.scope}


@router.post("/sync-codes/{code}/revoke")
async def admin_revoke_sync_code_route(
    code: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Make a pairing code unredeemable, regardless of its expiry."""
    sync_code = await db.get(SyncCode, code)
    if sync_code is None:
        raise HTTPException(status_code=404, detail="Sync code not found")
    sync_code.used = True
    await db.commit()
    logger.warning(
        "Admin action: revoke sync code",
        extra={"admin": admin.get("username"), "code": code},
    )
    return {"success": True, "code": code}
