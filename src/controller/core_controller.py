"""
Core API routes.
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import redis
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from src.db.session import async_session_factory, get_db
from src.handlers.llm_exception_handler import llm_exc_handler
from src.handlers.redis_exception_handler import redis_exc_handler
from src.models.core import (
    DataRequest,
    HistoryItem,
    RecentSearchesRequest,
    SearchRequest,
    SearchResponse,
)
from src.services.core_service.main import CoreRetrieval, Retrieval
from src.services.ingestion_service.ingestion import _default_heading_path, ingest_batch
from src.services.privacy_service.privacy import clear_all_data, clear_history
from src.services.search_history_service.search_history import (
    get_recent_searches,
    persist_search,
)
from src.services.sync_service.sync import resolve_sync_account_id
from src.utility.logger import AppLogger

logger = AppLogger.get_logger(__name__)

load_dotenv()

redis_host = os.getenv("REDIS_HOST")
redis_port = os.getenv("REDIS_PORT")

redis_client = redis.Redis(
    host=redis_host,
    port=int(redis_port) if redis_port else None,
    db=0,
    decode_responses=True,
)

router = APIRouter(prefix="/v1", tags=["Core"])


def _annotate_source_browser(docs: List[dict], requesting_browser_uuid: str) -> None:
    """Mark each doc with whether it came from a different linked browser
    than the one making this request.

    Computed here, not left to the frontend, so the client only has to
    render `metadata.found_on_other_browser` — no `browser_uuid` comparison
    logic needed client-side. `source_browser_uuid` is absent on BM25-only
    hits (not yet persisted to Postgres — see `rag.py::_merge_vector_hits`),
    so those always come back `False` rather than an uncertain/missing tag.
    """
    for doc in docs:
        metadata = doc.get("metadata")
        if metadata is None:
            continue
        source_browser_uuid = metadata.get("source_browser_uuid")
        metadata["found_on_other_browser"] = bool(source_browser_uuid) and (
            source_browser_uuid != requesting_browser_uuid
        )


async def _ingest_with_own_session(
    items: List[HistoryItem], sync_account_id: str, flag: str, browser_uuid: str
) -> None:
    """Run one flag's `ingest_batch` in its own `AsyncSession`.

    Lets history and bookmark ingestion run concurrently — a single
    `AsyncSession` isn't safe for concurrent use — and keeps their commits
    fully independent: history and bookmark rows are disjoint, so one
    flag's failure has no reason to affect the other's already-successful
    commit. Logs and swallows failures rather than raising, matching
    `_persist_embeddings`'s "don't fail /save-data over a Postgres hiccup".
    """
    try:
        async with async_session_factory() as db:
            await ingest_batch(
                items=items,
                user_id=sync_account_id,
                flag=flag,
                browser_uuid=browser_uuid,
                db=db,
            )
    except Exception as exc:
        logger.warning("Failed to persist %s embeddings to Postgres: %s", flag, exc)


async def _persist_embeddings(
    payload: DataRequest, sync_account_id: str, db: AsyncSession
) -> None:
    """Ingest a save-data payload into Postgres (entries + embeddings).

    Keyed by the resolved `sync_account_id`, not the raw browser id, so
    linked browsers share one history pool, cap, and pgvector index. The
    raw browser id (`payload.user_id`) is still threaded through
    separately as `source_browser_uuid` on each new page, for cross-
    browser result attribution. Combined mode runs history and bookmark
    ingestion concurrently (each in its own session) instead of
    sequentially, roughly halving the latency a pre-search flush blocks on.
    """
    if payload.flag == "combined":
        await asyncio.gather(
            _ingest_with_own_session(
                payload.data, sync_account_id, "history", payload.user_id
            ),
            _ingest_with_own_session(
                payload.bookmarks, sync_account_id, "bookmark", payload.user_id
            ),
        )
    else:
        try:
            await ingest_batch(
                items=payload.data,
                user_id=sync_account_id,
                flag=payload.flag,
                browser_uuid=payload.user_id,
                db=db,
            )
        except Exception as exc:
            logger.warning("Failed to persist embeddings to Postgres: %s", exc)


@router.post("/save-data", response_model=Dict[str, Any])
async def save_data(
    payload: DataRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    """Persist user history/bookmark data to Redis with a short TTL.
    For flag='combined', stores history and bookmarks under separate sub-keys.
    Keys are scoped to the requesting browser's resolved sync account, so
    paired browsers share the same cache. Also ingests the payload into
    Postgres so embeddings are persisted once, at save time, instead of
    being rebuilt on every search request.
    """
    body_bytes = await request.body()
    logger.info(
        "save-data payload: %.2f MB (%d bytes) | flag=%s | history_items=%d | "
        "bookmark_items=%d",
        len(body_bytes) / (1024 * 1024),
        len(body_bytes),
        payload.flag,
        len(payload.data),
        len(payload.bookmarks),
    )

    def _section_summary(item: HistoryItem, flag: str) -> dict:
        heading_path = _default_heading_path(item, flag)
        return {
            "url": item.url,
            "heading_path": heading_path,
            "content_len": len(item.content),
        }

    # payload.bookmarks only carries items when flag == "combined"; otherwise
    # payload.data itself holds whatever payload.flag says (history or
    # bookmark), so its items must be summarized with that flag, not a
    # hardcoded "history".
    data_flag = "history" if payload.flag == "combined" else payload.flag
    sections = [_section_summary(item, data_flag) for item in payload.data] + [
        _section_summary(item, "bookmark") for item in payload.bookmarks
    ]
    keys = [(s["url"], tuple(s["heading_path"])) for s in sections]
    duplicate_keys_in_batch = len(keys) - len(set(keys))

    logger.print(
        "save-data received",
        {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "browser_uuid": payload.user_id,
            "flag": payload.flag,
            "data_count": len(payload.data),
            "bookmark_count": len(payload.bookmarks),
            # >0 means some (url, heading_path) pairs repeat within this
            # batch — only the last occurrence of each survives ingestion.
            "duplicate_keys_in_batch": duplicate_keys_in_batch,
            "sections": sections,
        },
    )

    try:
        sync_account_id = await resolve_sync_account_id(
            browser_uuid=payload.user_id, db=db
        )
        await asyncio.to_thread(redis_client.ping)

        if payload.flag == "combined":
            history_payload = {"data": [item.dict() for item in payload.data]}
            bookmark_payload = {"data": [item.dict() for item in payload.bookmarks]}
            # Same keys a separate history/bookmark save writes — not a
            # parallel :ch/:cb namespace. The extension syncs history and
            # bookmarks as two independent /save-data calls in practice, so
            # a dedicated combined-only key was never getting populated;
            # reading/writing the same keys either sync path uses means
            # combined search sees whatever's actually cached, regardless
            # of which flag(s) wrote it.
            await asyncio.to_thread(
                redis_client.set,
                f"user:{sync_account_id}:history",
                json.dumps(history_payload),
                ex=3600,
            )
            await asyncio.to_thread(
                redis_client.set,
                f"user:{sync_account_id}:bookmark",
                json.dumps(bookmark_payload),
                ex=3600,
            )
        else:
            redis_key = f"user:{sync_account_id}:{payload.flag}"
            await asyncio.to_thread(
                redis_client.set, redis_key, payload.json(), ex=3600
            )

        await _persist_embeddings(
            payload=payload, sync_account_id=str(sync_account_id), db=db
        )

        return {"success": True, "message": "Data saved successfully"}

    except redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise HTTPException(
            status_code=500,
            detail={"success": False, "message": redis_exc_handler.map_exception(e)},
        ) from e

    except Exception as exc:
        logger.error(f"Error saving data: {exc}", "red")
        raise HTTPException(
            status_code=500,
            detail={"success": False, "message": redis_exc_handler.map_exception(exc)},
        )


@router.post("/search")
async def search(
    payload: SearchRequest,
    background_tasks: BackgroundTasks,
    service: CoreRetrieval = Depends(Retrieval.get_retrieval_service),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Run a non-streaming RAG search against the cached user data.
    Loads the stored history for the requesting browser's resolved sync
    account, so results span every browser linked to it. Persists a
    successful search into recent-searches as a background task.
    """
    sync_account_id = await resolve_sync_account_id(browser_uuid=payload.user_id, db=db)
    redis_key = f"user:{sync_account_id}:{payload.flag}"
    user_data = await asyncio.to_thread(redis_client.get, redis_key)
    history: dict = json.loads(user_data)
    try:
        history_data = history.get("data", [])
        start = time.monotonic()
        response = await service.invoke_rag(
            data=payload, history=history_data, user_id=str(sync_account_id), db=db
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        _annotate_source_browser(response.docs, payload.user_id)
        if response.success:
            background_tasks.add_task(
                persist_search,
                user_id=str(sync_account_id),
                query=payload.query,
                flag=payload.flag,
                answer=response.result,
                sources=response.docs,
                duration_ms=duration_ms,
            )
        return response
    except Exception as exc:
        logger.error(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "message": llm_exc_handler.map_exception(exc),
            },
        ) from exc


@router.post("/search-stream")
async def search_stream(
    payload: SearchRequest,
    service: CoreRetrieval = Depends(Retrieval.get_retrieval_service),
    db: AsyncSession = Depends(get_db),
):
    """Stream RAG search progress and results via Server-Sent Events.
    For flag='combined', loads history from `:history` and bookmarks from
    `:bookmark` — the same keys a plain history/bookmark sync writes, not a
    combined-only namespace, so combined search sees whatever's cached
    regardless of which flag(s) actually synced it. Keys and retrieval are
    scoped to the requesting browser's resolved sync account, so linked
    browsers see each other's history.
    Emits a final event with the full response or an error event. Persists
    a successful search into recent-searches after the stream completes.
    """
    sync_account_id = await resolve_sync_account_id(browser_uuid=payload.user_id, db=db)
    result_holder: dict = {}

    if payload.flag == "combined":
        # Reads the same keys a separate history/bookmark sync writes —
        # combined search isn't limited to data that arrived via a
        # combined-flagged save.
        history_raw = await asyncio.to_thread(
            redis_client.get, f"user:{sync_account_id}:history"
        )
        bookmark_raw = await asyncio.to_thread(
            redis_client.get, f"user:{sync_account_id}:bookmark"
        )
        history_data = json.loads(history_raw).get("data", []) if history_raw else []
        bookmark_data = json.loads(bookmark_raw).get("data", []) if bookmark_raw else []
    else:
        redis_key = f"user:{sync_account_id}:{payload.flag}"
        user_data = await asyncio.to_thread(redis_client.get, redis_key)
        history_data = json.loads(user_data).get("data", []) if user_data else []
        bookmark_data = []

    stream_start = time.monotonic()

    async def event_stream():
        try:
            if payload.flag == "combined":
                gen = service.stream_combined_rag(
                    data=payload,
                    history=history_data,
                    bookmarks=bookmark_data,
                    user_id=str(sync_account_id),
                    db=db,
                )
            else:
                gen = service.stream_rag(
                    data=payload,
                    history=history_data,
                    user_id=str(sync_account_id),
                    db=db,
                )
            async for event in gen:
                if event.get("step") == "final":
                    data = event.get("data") or {}
                    _annotate_source_browser(data.get("docs") or [], payload.user_id)
                    result_holder["data"] = data
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            logger.error(exc)
            error_event = {
                "step": "error",
                "data": {"message": llm_exc_handler.map_exception(exc=exc)},
            }
            yield f"data: {json.dumps(error_event)}\n\n"

    async def _persist_after_stream() -> None:
        data = result_holder.get("data")
        if data and data.get("success"):
            duration_ms = int((time.monotonic() - stream_start) * 1000)
            await persist_search(
                user_id=str(sync_account_id),
                query=payload.query,
                flag=payload.flag,
                answer=data.get("result", ""),
                sources=data.get("docs", []),
                duration_ms=duration_ms,
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        background=BackgroundTask(_persist_after_stream),
    )


@router.post("/recent-searches", response_model=Dict[str, Any])
async def recent_searches_route(
    payload: RecentSearchesRequest, db: AsyncSession = Depends(get_db)
):
    """Return this browser's (or its linked account's) most recent searches.

    POST, not GET — MV3 service workers don't reliably send an Origin
    header on GET requests, which broke nginx's Origin-allowlist check
    upstream.
    """
    sync_account_id = await resolve_sync_account_id(
        browser_uuid=payload.browser_uuid, db=db
    )
    searches = await get_recent_searches(
        user_id=str(sync_account_id), limit=payload.limit, db=db
    )
    return {"searches": searches}


@router.delete("/user/history", response_model=Dict[str, Any])
async def clear_history_route(browser_uuid: str, db: AsyncSession = Depends(get_db)):
    """Delete this account's history pages/sections/embeddings and Redis
    cache. Bookmarks, search history, and account/sync setup are untouched.
    Scoped to `sync_account_id`, so a synced user's delete reaches every
    linked browser, not just the requesting one.
    """
    try:
        sync_account_id = await resolve_sync_account_id(
            browser_uuid=browser_uuid, db=db
        )
        await clear_history(sync_account_id=sync_account_id, db=db)
        await asyncio.to_thread(redis_client.delete, f"user:{sync_account_id}:history")
        return {"status": "history_cleared"}
    except redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise HTTPException(
            status_code=500,
            detail={"success": False, "message": redis_exc_handler.map_exception(e)},
        ) from e


@router.delete("/user/data", response_model=Dict[str, Any])
async def clear_all_data_route(browser_uuid: str, db: AsyncSession = Depends(get_db)):
    """Full wipe: pages (history + bookmarks), sections, embeddings,
    search history, and the matching Redis cache. Does not touch the
    `sync_accounts`/`users`/`sync_codes` rows — account, tier, and browser
    links are preserved. Scoped to `sync_account_id`, so this clears every
    linked browser's data, not just the requesting one.
    """
    try:
        sync_account_id = await resolve_sync_account_id(
            browser_uuid=browser_uuid, db=db
        )
        await clear_all_data(sync_account_id=sync_account_id, db=db)
        await asyncio.to_thread(
            redis_client.delete,
            f"user:{sync_account_id}:history",
            f"user:{sync_account_id}:bookmark",
        )
        return {"status": "all_data_cleared"}
    except redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise HTTPException(
            status_code=500,
            detail={"success": False, "message": redis_exc_handler.map_exception(e)},
        ) from e
