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

from src.db.models import Page, SyncAccount, SyncCode, User
from src.services.ingestion_service.ingestion import _trim_to_cap
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


class AlreadySolo(Exception):
    """Raised when `unlink` is called for a browser not linked to anyone else.

    Unlinking a solo browser has no effect on it (same browser, same data)
    but leaves its old account behind as empty, orphaned row — pure debris,
    not a meaningful action. Callers should only offer "unlink" once an
    account is actually linked (`browser_count > 1`).
    """


class AccountStillLinked(Exception):
    """Raised when `delete_account` is called on an account with 2+ browsers.

    Deleting a linked account would silently orphan every other browser
    still pointing at it — callers must unlink them first, one at a time,
    so each browser explicitly keeps its own data.
    """


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
        current_count = count_result.scalar_one()
        if current_count >= settings.sync_code_rate_limit_per_hour:
            logger.warning(
                "Sync code rate limit hit",
                extra={"sync_account_id": sync_account_id, "count": current_count},
            )
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


async def _migrate_browser_pages(
    old_account_id: int, new_account_id: int, browser_uuid: str, db: AsyncSession
) -> None:
    """Reassign a browser's pre-pairing pages onto its new shared account.

    Scoped to this browser's own contributions (`source_browser_uuid`), not
    every page on `old_account_id` — that old account might itself already
    have other browsers linked to it, and only this one browser's data
    should move. On a `(user_id, url_hash, flag)` collision (both accounts
    independently visited the same URL before pairing), keeps whichever
    page was visited more recently and drops the other — cascades to its
    sections/embeddings — consistent with this codebase's existing
    "recency wins" retention philosophy (`_trim_to_cap` already evicts
    oldest-first).
    """
    result = await db.execute(
        select(Page).where(
            Page.user_id == old_account_id,
            Page.source_browser_uuid == browser_uuid,
        )
    )
    pages_to_migrate = result.scalars().all()

    for page in pages_to_migrate:
        try:
            async with db.begin_nested():
                await db.execute(
                    update(Page)
                    .where(Page.id == page.id)
                    .values(user_id=new_account_id)
                )
        except IntegrityError:
            existing = await db.execute(
                select(Page).where(
                    Page.user_id == new_account_id,
                    Page.url_hash == page.url_hash,
                    Page.flag == page.flag,
                )
            )
            existing_page = existing.scalar_one()
            if page.visited_at > existing_page.visited_at:
                async with db.begin_nested():
                    await db.execute(delete(Page).where(Page.id == existing_page.id))
                    await db.execute(
                        update(Page)
                        .where(Page.id == page.id)
                        .values(user_id=new_account_id)
                    )
            else:
                async with db.begin_nested():
                    await db.execute(delete(Page).where(Page.id == page.id))


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

    # Migrate any pages this browser already ingested before pairing —
    # otherwise they'd stay stranded under its old (now-unreachable) solo
    # account id, since _set_sync_account below only repoints identity
    # resolution going forward, not already-persisted data.
    existing = await db.execute(
        select(User.sync_account_id).where(User.browser_uuid == browser_uuid)
    )
    old_account_id = existing.scalar_one_or_none()
    if old_account_id is not None and old_account_id != sync_account_id:
        await _migrate_browser_pages(old_account_id, sync_account_id, browser_uuid, db)
        await _trim_to_cap(user_id=str(sync_account_id), flag="history", db=db)
        await _trim_to_cap(user_id=str(sync_account_id), flag="bookmark", db=db)

    await _set_sync_account(browser_uuid, sync_account_id, db)
    await db.commit()
    return sync_account_id


async def unlink(browser_uuid: str, db: AsyncSession) -> int:
    """Repoint this browser onto a fresh solo sync account.

    Other browsers still linked to the previous account are untouched. Takes
    this browser's own contributed pages with it (matched via
    `source_browser_uuid`) — otherwise unlinking would silently strand the
    browser's own history on the shared account it's leaving, with no way
    back. The new account is freshly created and empty, so unlike pairing's
    `_migrate_browser_pages`, there's no possible url_hash/flag collision to
    resolve here — a plain reassignment is safe.

    Raises `AlreadySolo` if this browser isn't currently linked to any other
    browser — see that exception's docstring for why this isn't just a
    no-op to allow through.
    """
    existing = await db.execute(
        select(User.sync_account_id).where(User.browser_uuid == browser_uuid)
    )
    old_account_id = existing.scalar_one_or_none()

    if old_account_id is not None:
        count_result = await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.sync_account_id == old_account_id)
        )
        if count_result.scalar_one() <= 1:
            raise AlreadySolo(
                f"Browser {browser_uuid} is not linked to any other browser"
            )

    account = SyncAccount()
    db.add(account)
    await db.flush()

    if old_account_id is not None:
        await db.execute(
            update(Page)
            .where(
                Page.user_id == old_account_id,
                Page.source_browser_uuid == browser_uuid,
            )
            .values(user_id=account.id)
        )

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


async def delete_account(sync_account_id: int, db: AsyncSession) -> None:
    """Permanently delete a solo account and all its data.

    Admin-only operation (no end-user equivalent — users get `unlink` and
    `clear-data`, not full account deletion). Requires the account to
    already be solo (0 or 1 linked browsers); raises `AccountStillLinked`
    otherwise rather than silently dropping every other linked browser's
    access.

    `sync_codes` has no `ondelete` cascade on `sync_account_id` (unlike
    `pages`/`users`/`search_history`, which are `ON DELETE CASCADE`), so
    any of this account's codes are deleted explicitly first — otherwise
    the `SyncAccount` delete below would fail with a FK violation.
    `llm_usage.sync_account_id` is `ON DELETE SET NULL`, deliberately: past
    token-usage stats are a historical record, not user data, so they
    outlive the account.
    """
    count_result = await db.execute(
        select(func.count())
        .select_from(User)
        .where(User.sync_account_id == sync_account_id)
    )
    browser_count = count_result.scalar_one()
    if browser_count > 1:
        raise AccountStillLinked(
            f"Account {sync_account_id} has {browser_count} linked browsers — "
            "unlink them first"
        )

    await db.execute(
        delete(SyncCode).where(SyncCode.sync_account_id == sync_account_id)
    )
    result = await db.execute(
        delete(SyncAccount).where(SyncAccount.id == sync_account_id)
    )
    await db.commit()
    if result.rowcount == 0:
        raise ValueError(f"Account {sync_account_id} not found")
