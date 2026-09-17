"""Cross-browser sync pairing routes.

Lets a browser generate a short-lived code, another browser redeem it to
join the same sync account, and a browser unlink back to a solo account.
Delegates all account/code logic to `src.services.sync_service.sync`.
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.models.core import (
    GenerateCodeRequest,
    RedeemCodeRequest,
    SyncStatusRequest,
    UnlinkRequest,
)
from src.services.sync_service.sync import (
    InvalidSyncCode,
    RateLimitExceeded,
    generate_code,
    get_sync_status,
    redeem_code,
    unlink,
)
from src.utility.logger import AppLogger

logger = AppLogger.get_logger(__name__)

router = APIRouter(prefix="/v1/sync", tags=["Sync"])


@router.post("/generate-code", response_model=Dict[str, Any])
async def generate_code_route(
    payload: GenerateCodeRequest, db: AsyncSession = Depends(get_db)
):
    """Issue a pairing code for the requesting browser's sync account."""
    try:
        code, expires_at = await generate_code(browser_uuid=payload.browser_uuid, db=db)
        return {"success": True, "code": code, "expiresAt": expires_at.isoformat()}
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429, detail={"success": False, "message": str(exc)}
        )


@router.post("/redeem-code", response_model=Dict[str, Any])
async def redeem_code_route(
    payload: RedeemCodeRequest, db: AsyncSession = Depends(get_db)
):
    """Join the requesting browser to the sync account behind `code`."""
    try:
        sync_account_id = await redeem_code(
            code=payload.code, browser_uuid=payload.browser_uuid, db=db
        )
        return {"success": True, "syncAccountId": sync_account_id}
    except InvalidSyncCode as exc:
        raise HTTPException(
            status_code=400, detail={"success": False, "message": str(exc)}
        )


@router.post("/unlink", response_model=Dict[str, Any])
async def unlink_route(payload: UnlinkRequest, db: AsyncSession = Depends(get_db)):
    """Repoint the requesting browser onto a fresh solo sync account."""
    sync_account_id = await unlink(browser_uuid=payload.browser_uuid, db=db)
    return {"success": True, "syncAccountId": sync_account_id}


@router.post("/status", response_model=Dict[str, Any])
async def sync_status_route(
    payload: SyncStatusRequest, db: AsyncSession = Depends(get_db)
):
    """Return the requesting browser's sync/link status.

    POST, not GET — MV3 service workers don't reliably send an Origin
    header on GET requests, which broke nginx's Origin-allowlist check
    upstream. Otherwise unchanged: always 200, a browser that's never made
    contact is a normal "not yet linked" status (`sync_account_id: null`),
    not an error, and this never auto-creates an account (read-only).
    """
    return await get_sync_status(browser_uuid=payload.browser_uuid, db=db)
