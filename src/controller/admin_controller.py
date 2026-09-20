"""Admin routes: login, and read-only server/data status.

Login issues a JWT (`admin_service.create_token`); every route below it is
gated by `get_current_admin`, which requires a valid `Authorization: Bearer
<token>` header. Admin accounts are provisioned only via
`scripts/create_admin.py` — there's no public registration endpoint.
"""

import asyncio
import shutil
import subprocess
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

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
from src.services.sync_service.sync import (
    AccountStillLinked,
    AlreadySolo,
    delete_account,
    unlink,
)
from src.utility.logger import AppLogger
from src.utility.pricing import estimate_cost_usd
from src.utility.settings import settings

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

    services = {
        name: await asyncio.to_thread(_check_systemd_service, name)
        for name in settings.systemd_services
    }

    return {
        "postgres": postgres,
        "pgvector": pgvector,
        "redis": redis_status,
        "services": services,
        "disk": _disk_usage(),
    }


def _check_systemd_service(name: str) -> dict:
    """`systemctl is-active <name>` — sync, always called via `asyncio.to_thread`.

    `{ok: false, detail: ...}` (never raises) when `systemctl` isn't
    available at all — e.g. local dev, a non-systemd host — same
    graceful-degradation shape as the nginx-log-file check.
    """
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = result.stdout.strip()
        return {"ok": status == "active", "status": status}
    except FileNotFoundError:
        return {"ok": False, "status": None, "detail": "systemctl not available"}
    except Exception as exc:
        return {"ok": False, "status": None, "detail": str(exc)}


def _disk_usage() -> dict:
    """Disk usage for the root filesystem — stdlib, no subprocess needed."""
    total, used, free = shutil.disk_usage("/")
    gb = 1024**3
    return {
        "totalGb": round(total / gb, 2),
        "usedGb": round(used / gb, 2),
        "freeGb": round(free / gb, 2),
        "usedPercent": round(used / total * 100, 1),
    }


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

    usage = []
    total_cost_usd = 0.0
    unpriced_rows = 0
    for row in result.all():
        cost_usd = estimate_cost_usd(
            row.provider, row.model, row.input_tokens, row.output_tokens
        )
        if cost_usd is None:
            unpriced_rows += 1
        else:
            total_cost_usd += cost_usd
        usage.append(
            {
                "useCase": row.use_case,
                "provider": row.provider,
                "model": row.model,
                "inputTokens": row.input_tokens,
                "outputTokens": row.output_tokens,
                "calls": row.calls,
                "costUsd": cost_usd,
            }
        )

    return {
        "usage": usage,
        "totalCostUsd": round(total_cost_usd, 4),
        "unpricedRows": unpriced_rows,
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


@router.get("/accounts")
async def list_accounts_route(
    browser_uuid: Optional[str] = Query(default=None),
    sort_by: Literal["activity_score", "created_at", "browser_count"] = Query(
        default="created_at"
    ),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """Paginated, sortable list of accounts.

    Solves the "I don't have an id to look up" gap: pass `browser_uuid`
    (substring match) to resolve which account a known browser belongs to,
    or omit it to just browse everything. Each row includes a lightweight
    activity summary (page/search/token counts) plus a 0-100
    `activityScore` — see `_activity_scores` — so the list is scannable
    without opening every row. Use `GET /accounts/{id}` for the full detail
    (browser list, etc.) once you have the id.

    `sort_by=activity_score`/`browser_count` aren't real database columns
    (they're computed from other tables), so sorting by them can't be a
    plain SQL `ORDER BY` + `LIMIT`/`OFFSET` — that would only sort *within*
    whatever page the DB happened to return, which is wrong the moment
    there's more than one page. Instead: fetch every matching account
    (respecting `browser_uuid`, before pagination), compute each one's
    sort key, sort the full set in Python, then slice `offset:offset+limit`
    — correct at any page, and cheap at this tool's scale (this repo has
    dozens of accounts, not millions).
    """
    base_query = select(SyncAccount)
    if browser_uuid:
        matching_ids = (
            select(User.sync_account_id)
            .where(User.browser_uuid.ilike(f"%{browser_uuid}%"))
            .distinct()
        )
        base_query = base_query.where(SyncAccount.id.in_(matching_ids))

    total = (
        await db.execute(select(func.count()).select_from(base_query.subquery()))
    ).scalar_one()

    all_accounts_result = await db.execute(base_query)
    all_accounts = all_accounts_result.scalars().all()
    all_account_ids = [account.id for account in all_accounts]

    browser_counts_result = await db.execute(
        select(User.sync_account_id, func.count())
        .where(User.sync_account_id.in_(all_account_ids))
        .group_by(User.sync_account_id)
    )
    browser_counts = dict(browser_counts_result.all())

    pages_by_account, searches_by_account, tokens_by_account = await _page_metrics(
        db, all_account_ids
    )
    scores = await _activity_scores(
        db, all_account_ids, pages_by_account, searches_by_account, tokens_by_account
    )

    reverse = sort_order == "desc"
    if sort_by == "activity_score":
        all_accounts.sort(key=lambda a: scores.get(a.id, 0.0), reverse=reverse)
    elif sort_by == "browser_count":
        all_accounts.sort(key=lambda a: browser_counts.get(a.id, 0), reverse=reverse)
    else:
        all_accounts.sort(key=lambda a: a.created_at, reverse=reverse)

    page_accounts = all_accounts[offset : offset + limit]

    return {
        "accounts": [
            {
                "syncAccountId": account.id,
                "tier": account.tier,
                "browserCount": browser_counts.get(account.id, 0),
                "isLinked": browser_counts.get(account.id, 0) > 1,
                "createdAt": account.created_at.isoformat(),
                "pagesTotal": pages_by_account.get(account.id, 0),
                "searchCount": searches_by_account.get(account.id, 0),
                "llmTokensTotal": tokens_by_account.get(account.id, 0),
                "activityScore": scores[account.id],
            }
            for account in page_accounts
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def _page_metrics(
    db: AsyncSession, account_ids: list[int]
) -> tuple[dict, dict, dict]:
    """Per-account totals for the given ids: pages, searches, LLM tokens."""
    if not account_ids:
        return {}, {}, {}

    pages_result = await db.execute(
        select(Page.user_id, func.count())
        .where(Page.user_id.in_(account_ids))
        .group_by(Page.user_id)
    )
    pages_by_account = dict(pages_result.all())

    searches_result = await db.execute(
        select(SearchHistory.user_id, func.count())
        .where(SearchHistory.user_id.in_(account_ids))
        .group_by(SearchHistory.user_id)
    )
    searches_by_account = dict(searches_result.all())

    tokens_result = await db.execute(
        select(
            LLMUsage.sync_account_id,
            func.sum(LLMUsage.input_tokens + LLMUsage.output_tokens),
        )
        .where(LLMUsage.sync_account_id.in_(account_ids))
        .group_by(LLMUsage.sync_account_id)
    )
    tokens_by_account = dict(tokens_result.all())

    return pages_by_account, searches_by_account, tokens_by_account


async def _activity_scores(
    db: AsyncSession,
    account_ids: list[int],
    pages_by_account: dict,
    searches_by_account: dict,
    tokens_by_account: dict,
) -> dict:
    """0-100 activity score (float, 2 decimal places) per account id,
    equally weighting 3 signals: total pages, search count, total LLM
    tokens. Left unrounded to whole numbers on purpose — two accounts that
    are close but not equal in activity should show as different scores,
    not collapse to the same integer.

    Each signal is min-max normalized against the max value for that
    signal across **all** accounts (not just the current page/filter), so
    a score of e.g. 80.42 means the same thing regardless of which page or
    `browser_uuid` filter produced this row — the three normalized signals
    are then averaged with equal weight (per explicit product decision:
    no single signal — e.g. LLM cost — dominates the score).
    """
    if not account_ids:
        return {}

    pages_counts = (
        select(func.count().label("cnt")).select_from(Page).group_by(Page.user_id)
    ).subquery()
    max_pages = (
        await db.execute(select(func.max(pages_counts.c.cnt)))
    ).scalar_one() or 0

    search_counts = (
        select(func.count().label("cnt"))
        .select_from(SearchHistory)
        .group_by(SearchHistory.user_id)
    ).subquery()
    max_searches = (
        await db.execute(select(func.max(search_counts.c.cnt)))
    ).scalar_one() or 0

    token_sums = (
        select(func.sum(LLMUsage.input_tokens + LLMUsage.output_tokens).label("tok"))
        .select_from(LLMUsage)
        .group_by(LLMUsage.sync_account_id)
    ).subquery()
    max_tokens = (
        await db.execute(select(func.max(token_sums.c.tok)))
    ).scalar_one() or 0

    def _normalize(value: int, max_value: int) -> float:
        if not max_value:
            return 0.0
        return min(value / max_value, 1.0) * 100

    return {
        account_id: round(
            (
                _normalize(pages_by_account.get(account_id, 0), max_pages)
                + _normalize(searches_by_account.get(account_id, 0), max_searches)
                + _normalize(tokens_by_account.get(account_id, 0), max_tokens)
            )
            / 3,
            2,
        )
        for account_id in account_ids
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
    `unlink` resolves the browser's actual current account itself. 400s if
    the browser isn't currently linked to anyone (see `AlreadySolo`) — has
    no effect and just leaves a fresh orphaned account, so this isn't a
    meaningful action to allow through.
    """
    try:
        new_account_id = await unlink(browser_uuid=payload.browser_uuid, db=db)
    except AlreadySolo as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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


@router.delete("/accounts/{sync_account_id}")
async def admin_delete_account_route(
    sync_account_id: int,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Permanently delete a solo (0 or 1 browser) account and all its data.

    409s with `AccountStillLinked`'s message if the account still has 2+
    linked browsers — unlink them first, one at a time, via
    `unlink-browser` above. Cascades to pages/sections/embeddings/search
    history; LLM usage stats are preserved (`sync_account_id` set to
    `NULL`), matching `delete_account`'s own retention reasoning.
    """
    browsers_result = await db.execute(
        select(User.browser_uuid).where(User.sync_account_id == sync_account_id)
    )
    browsers = [row[0] for row in browsers_result.all()]

    try:
        await delete_account(sync_account_id, db)
    except AccountStillLinked as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    logger.warning(
        "Admin action: delete account",
        extra={
            "admin": admin.get("username"),
            "sync_account_id": sync_account_id,
            "browser_uuid": browsers[0] if browsers else None,
        },
    )
    return {"success": True, "deletedSyncAccountId": sync_account_id}


def _tail_log_file(
    path: str, limit: int, search: Optional[str]
) -> tuple[list[str], Optional[str]]:
    """Return up to `limit` most-recent lines from `path`, oldest first.

    `search` (case-insensitive substring) filters as it goes, so the result
    is "the last `limit` matching lines," not "the last `limit` lines,
    then filtered" — the latter could come back short or empty whenever
    matches are sparse near the end of a busy log file. Runs synchronously
    (blocking file I/O) — always called via `asyncio.to_thread`.
    """
    try:
        matching: deque[str] = deque(maxlen=limit)
        with open(path, "r", errors="replace") as f:
            for line in f:
                if search and search.lower() not in line.lower():
                    continue
                matching.append(line.rstrip("\n"))
        return list(matching), None
    except FileNotFoundError:
        return [], f"Log file not found: {path}"
    except PermissionError:
        return [], f"Permission denied reading: {path}"
    except Exception as exc:
        return [], str(exc)


@router.get("/status/nginx-logs")
async def nginx_logs_route(
    log_type: Literal["error", "access"] = Query(default="error"),
    limit: int = Query(default=100, le=1000),
    search: Optional[str] = Query(default=None),
    _admin: dict = Depends(get_current_admin),
):
    """Tail nginx's error/access log directly off disk.

    Unlike `/status/logs`, this isn't backed by `app_logs` — nginx runs as
    its own process outside this app, so its log files on disk are the
    only source (paths from `settings.nginx_error_log_path`/
    `nginx_access_log_path`, standard Debian/Ubuntu locations by default).
    `available: false` (not an error response) when the file can't be
    read — e.g. running locally with no nginx, or a permissions issue —
    so the caller can distinguish "no logs to show" from a broken request.
    """
    path = (
        settings.nginx_error_log_path
        if log_type == "error"
        else settings.nginx_access_log_path
    )
    lines, detail = await asyncio.to_thread(_tail_log_file, path, limit, search)
    return {
        "logType": log_type,
        "lines": lines,
        "available": detail is None,
        "detail": detail,
    }
