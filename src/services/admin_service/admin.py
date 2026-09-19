"""Admin authentication: credential verification and JWT issuance/decoding.

Admins are created only via `scripts/create_admin.py` — there's no public
registration endpoint, so `AdminUser` rows are always operator-provisioned.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AdminUser
from src.utility.settings import settings

JWT_ALGORITHM = "HS256"


class InvalidAdminToken(Exception):
    """Raised when an admin bearer token is missing, malformed, or expired."""


async def verify_admin(
    username: str, password: str, db: AsyncSession
) -> Optional[AdminUser]:
    """Return the matching `AdminUser` if `password` is correct, else `None`."""
    result = await db.execute(select(AdminUser).where(AdminUser.username == username))
    admin = result.scalar_one_or_none()
    if admin is None:
        return None
    if not bcrypt.checkpw(
        password.encode("utf-8"), admin.password_hash.encode("utf-8")
    ):
        return None
    return admin


def create_token(admin_id: int, username: str) -> tuple[str, datetime]:
    """Issue a signed JWT for this admin, valid for `admin_token_expiry_minutes`."""
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.admin_token_expiry_minutes
    )
    payload = {"sub": str(admin_id), "username": username, "exp": expires_at}
    token = jwt.encode(payload, settings.admin_jwt_secret, algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_token(token: str) -> dict:
    """Return the token's payload, or raise `InvalidAdminToken`."""
    try:
        return jwt.decode(token, settings.admin_jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidAdminToken(str(exc)) from exc
