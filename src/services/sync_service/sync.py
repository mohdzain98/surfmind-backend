"""Cross-browser sync account resolution, pairing, and unlink.

Maps each browser's own id (`browser_uuid`, what the extension already
sends as `user_id`) to a shared `sync_account_id` via `users`. Pairing
repoints a browser's account; everything downstream (Redis keys, ingestion,
retrieval) is keyed off the resolved account id, not the raw browser id.
"""

import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Tuple

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import SyncAccount, SyncCode, User
from src.utility.logger import AppLogger
from src.utility.settings import settings

logger = AppLogger.get_logger(__name__)

CODE_LENGTH = 8
RATE_LIMIT_WINDOW = timedelta(hours=1)
_CODE_ALPHABET = string.ascii_uppercase + string.digits


class RateLimitExceeded(Exception):
    """Raised when an account requests more codes than the hourly limit."""


class InvalidSyncCode(Exception):
    """Raised when a redeemed code is missing, expired, or already used."""


async def resolve_sync_account_id(browser_uuid: str, db: AsyncSession) -> int:
    """Return this browser's sync account id, auto-creating one on first contact.

    Solo browsers get a fresh 1:1 `SyncAccount` the first time they're seen;
    every request after that resolves to the same (possibly paired) account.
    """
    existing = await db.execute(
        select(User.sync_account_id).where(User.browser_uuid == browser_uuid)
    )
    account_id = existing.scalar_one_or_none()
    if account_id is not None:
        return account_id

    account = SyncAccount()
    db.add(account)
    await db.flush()

    stmt = (
        pg_insert(User)
        .values(browser_uuid=browser_uuid, sync_account_id=account.id)
        .on_conflict_do_nothing(index_elements=["browser_uuid"])
        .returning(User.sync_account_id)
    )
    result = await db.execute(stmt)
    account_id = result.scalar_one_or_none()
    if account_id is None:
        # Lost a race with a concurrent first-contact insert — use its account.
        existing = await db.execute(
            select(User.sync_account_id).where(User.browser_uuid == browser_uuid)
        )
        account_id = existing.scalar_one()
    await db.commit()
    return account_id


async def _set_sync_account(
    browser_uuid: str, sync_account_id: int, db: AsyncSession
) -> None:
    """Point this browser at `sync_account_id`, creating its User row if needed."""
    stmt = pg_insert(User).values(
        browser_uuid=browser_uuid, sync_account_id=sync_account_id
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["browser_uuid"],
        set_={"sync_account_id": sync_account_id},
    )
    await db.execute(stmt)


async def _delete_expired_codes(sync_account_id: int, db: AsyncSession) -> None:
    """Lazily clean up this account's expired codes (no cron job in this repo)."""
    await db.execute(
        delete(SyncCode).where(
            SyncCode.sync_account_id == sync_account_id,
            SyncCode.expires_at < func.now(),
        )
    )


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LENGTH))


async def generate_code(browser_uuid: str, db: AsyncSession) -> Tuple[str, datetime]:
    """Issue a short-lived pairing code for this browser's sync account.

    Raises `RateLimitExceeded` past the dev/prod-tiered hourly limit
    (`sync.code_rate_limit_per_hour` in `config/params.yml`). Returns the
    code and its expiry — that's all the endpoint needs for its response.
    """
    sync_account_id = await resolve_sync_account_id(browser_uuid, db)
    await _delete_expired_codes(sync_account_id, db)
    await db.commit()  # persist cleanup regardless of the rate-limit outcome

    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.sync_code_expiry_minutes
    )
    for _ in range(5):
        # Serializes concurrent generate_code calls for this SAME account
        # so the count-then-insert check below can't race (TOCTOU): without
        # this, concurrent requests can all see "under limit" before any of
        # them commits its insert, letting the count overshoot the cap.
        # Different accounts aren't blocked by each other. Held for the
        # rest of this transaction, released automatically on
        # commit/rollback — re-acquired every loop iteration since a
        # rollback (on code collision) ends the transaction and releases it.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:id)"), {"id": sync_account_id}
        )

        window_start = datetime.now(timezone.utc) - RATE_LIMIT_WINDOW
        count_result = await db.execute(
            select(func.count())
            .select_from(SyncCode)
            .where(
                SyncCode.sync_account_id == sync_account_id,
                SyncCode.created_at >= window_start,
            )
        )
        if count_result.scalar_one() >= settings.sync_code_rate_limit_per_hour:
            raise RateLimitExceeded(
                f"Rate limit exceeded for account {sync_account_id}"
            )

        code = _generate_code()
        db.add(
            SyncCode(
                code=code,
                sync_account_id=sync_account_id,
                expires_at=expires_at,
                used=False,
            )
        )
        try:
            await db.commit()
            return code, expires_at
        except IntegrityError:
            await db.rollback()

    raise RuntimeError("Failed to generate a unique sync code")


async def redeem_code(code: str, browser_uuid: str, db: AsyncSession) -> int:
    """Repoint this browser onto the code's sync account.

    Raises `InvalidSyncCode` if the code doesn't exist, has expired, or was
    already used. Claims the code via a single atomic
    `UPDATE ... WHERE used = false ... RETURNING`, not a SELECT-then-UPDATE
    — the latter lets two concurrent redemptions both read `used = false`
    before either commits, so both pass the check and both redeem the same
    code. Postgres's row lock on the UPDATE means only one concurrent
    caller can ever win the `used = false → true` transition.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(SyncCode)
        .where(
            SyncCode.code == code,
            SyncCode.used.is_(False),
            SyncCode.expires_at >= now,
        )
        .values(used=True)
        .returning(SyncCode.sync_account_id)
    )
    sync_account_id = result.scalar_one_or_none()

    if sync_account_id is None:
        # Lost the race, or never had a shot — figure out which error fits.
        check = await db.execute(select(SyncCode).where(SyncCode.code == code))
        sync_code = check.scalar_one_or_none()
        if sync_code is None:
            raise InvalidSyncCode("Code not found")
        if sync_code.used:
            raise InvalidSyncCode("Code already used")
        raise InvalidSyncCode("Code expired")

    await _set_sync_account(browser_uuid, sync_account_id, db)
    await db.commit()
    return sync_account_id


async def unlink(browser_uuid: str, db: AsyncSession) -> int:
    """Repoint this browser onto a fresh solo sync account.

    Other browsers still linked to the previous account are untouched.
    """
    account = SyncAccount()
    db.add(account)
    await db.flush()

    await _set_sync_account(browser_uuid, account.id, db)
    await db.commit()
    return account.id


async def get_sync_status(browser_uuid: str, db: AsyncSession) -> dict:
    """Return this browser's sync status.

    Read-only — unlike `resolve_sync_account_id`, this never auto-creates a
    `User`/`SyncAccount` row. A browser that's never made contact is a
    normal "not yet linked" status, not an error: `sync_account_id` is
    `None` and `browser_count` is 1.
    """
    result = await db.execute(
        select(User.sync_account_id).where(User.browser_uuid == browser_uuid)
    )
    sync_account_id = result.scalar_one_or_none()
    if sync_account_id is None:
        return {
            "is_linked": False,
            "browser_count": 1,
            "sync_account_id": None,
            "tier": "free",
        }

    count_result = await db.execute(
        select(func.count())
        .select_from(User)
        .where(User.sync_account_id == sync_account_id)
    )
    browser_count = count_result.scalar_one()

    tier_result = await db.execute(
        select(SyncAccount.tier).where(SyncAccount.id == sync_account_id)
    )
    tier = tier_result.scalar_one_or_none() or "free"

    return {
        "is_linked": browser_count > 1,
        "browser_count": browser_count,
        "sync_account_id": sync_account_id,
        "tier": tier,
    }
