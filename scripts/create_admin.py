"""Provision a new admin account.

Admins are never created through a public API endpoint — this script is the
only way. Prompts for the password via `getpass` (never a plain CLI arg or
log line), hashes it with bcrypt, and inserts the row.

Uses this repo's own DB connection setup (src.db.session), so it connects
the same way whether run on a laptop or on the deployed server — this
script itself is tracked and deployed for that reason.

Usage:
    python -m scripts.create_admin --username <name>
"""

import argparse
import asyncio
import getpass

import bcrypt
from sqlalchemy import select

from src.db.models import AdminUser
from src.db.session import async_session_factory


async def create_admin(username: str, password: str) -> None:
    async with async_session_factory() as db:
        existing = await db.execute(
            select(AdminUser).where(AdminUser.username == username)
        )
        if existing.scalar_one_or_none() is not None:
            print(f"Admin '{username}' already exists — nothing to do.")
            return

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        db.add(AdminUser(username=username, password_hash=password_hash))
        await db.commit()
        print(f"Admin '{username}' created.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a new admin account")
    parser.add_argument("--username", required=True)
    args = parser.parse_args()

    entered_password = getpass.getpass("Password: ")
    confirm_password = getpass.getpass("Confirm password: ")
    if entered_password != confirm_password:
        raise SystemExit("Passwords did not match.")
    if len(entered_password) < 8:
        raise SystemExit("Password must be at least 8 characters.")

    asyncio.run(create_admin(args.username, entered_password))
