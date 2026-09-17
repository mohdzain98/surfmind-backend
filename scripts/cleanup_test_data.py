"""One-off cleanup for load-test-generated data.

Deletes every sync account whose browser_uuid carries the `loadtest-`
prefix — the identity marker the (local-only, gitignored) load-testing
tools in load_tests/ tag every simulated user with. Real users never get
this prefix, so it's safe to run against a real server's database,
including prod, after running load tests against it from elsewhere — this
script itself is tracked and deployed, so it can run directly on the
server, without needing the load-test tooling to be present there too.

Uses this repo's own DB/Redis connection setup (src.db.session,
REDIS_HOST/REDIS_PORT from .env), so it connects the same way whether run
on a laptop or on the deployed server.

Defaults to a dry run — lists what would be deleted, deletes nothing.
Pass --yes to actually delete.

Usage:
    python -m scripts.cleanup_test_data              # dry run
    python -m scripts.cleanup_test_data --yes         # actually delete
"""

import argparse
import asyncio
import os

import redis
from dotenv import load_dotenv
from sqlalchemy import delete, func, select

from src.db.models import Page, SearchHistory, SyncAccount, SyncCode, User
from src.db.session import async_session_factory

PREFIX = "loadtest-"

load_dotenv()


def _redis_client() -> redis.Redis:
    return redis.Redis(
        host=os.getenv("REDIS_HOST"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=0,
        decode_responses=True,
    )


async def cleanup(confirm: bool) -> None:
    async with async_session_factory() as db:
        account_ids_result = await db.execute(
            select(User.sync_account_id)
            .distinct()
            .where(User.browser_uuid.like(f"{PREFIX}%"))
        )
        account_ids = [row[0] for row in account_ids_result]

        if not account_ids:
            print("No load-test accounts found — nothing to clean up.")
            return

        users_count = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.browser_uuid.like(f"{PREFIX}%"))
        )
        pages_count = await db.scalar(
            select(func.count()).select_from(Page).where(Page.user_id.in_(account_ids))
        )
        search_history_count = await db.scalar(
            select(func.count())
            .select_from(SearchHistory)
            .where(SearchHistory.user_id.in_(account_ids))
        )
        sync_codes_count = await db.scalar(
            select(func.count())
            .select_from(SyncCode)
            .where(SyncCode.sync_account_id.in_(account_ids))
        )

        print(f"Load-test accounts found: {len(account_ids)}")
        print(f"  users (browser_uuid rows): {users_count}")
        print(f"  pages (cascades to sections/embeddings): {pages_count}")
        print(f"  search_history rows: {search_history_count}")
        print(f"  sync_codes: {sync_codes_count}")
        print(
            f"  Redis keys: up to {len(account_ids) * 2} "
            "(:history/:bookmark per account)"
        )

        if not confirm:
            print("\nDry run — nothing deleted. Pass --yes to actually delete.")
            return

        await db.execute(delete(Page).where(Page.user_id.in_(account_ids)))
        await db.execute(
            delete(SearchHistory).where(SearchHistory.user_id.in_(account_ids))
        )
        await db.execute(
            delete(SyncCode).where(SyncCode.sync_account_id.in_(account_ids))
        )
        await db.execute(
            User.__table__.delete().where(User.browser_uuid.like(f"{PREFIX}%"))
        )
        # Safety check via NOT IN, not a blanket delete by id — in the
        # unlikely case any real (non-loadtest) browser ever linked to one
        # of these accounts, its row keeps the account alive here rather
        # than silently deleting a real user's account.
        remaining_owners = await db.execute(
            select(User.sync_account_id).where(User.sync_account_id.in_(account_ids))
        )
        still_owned = {row[0] for row in remaining_owners}
        deletable_account_ids = [aid for aid in account_ids if aid not in still_owned]
        await db.execute(
            delete(SyncAccount).where(SyncAccount.id.in_(deletable_account_ids))
        )
        await db.commit()

        redis_client = _redis_client()
        for account_id in account_ids:
            redis_client.delete(
                f"user:{account_id}:history", f"user:{account_id}:bookmark"
            )

        print(f"\nDeleted {len(account_ids)} load-test accounts and their data.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean up load-test-generated data")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="actually delete (default is a dry run that only reports counts)",
    )
    args = parser.parse_args()
    asyncio.run(cleanup(confirm=args.yes))
