"""Async SQLAlchemy engine/session setup for Postgres.

Provides the shared async engine, session factory, and a FastAPI
dependency (`get_db`) that request handlers use to obtain a scoped
`AsyncSession` for the lifetime of a single request.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.utility.provider import SecretsProvider

engine: AsyncEngine = create_async_engine(SecretsProvider.get_database_url())
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped `AsyncSession`, closing it afterwards."""
    async with async_session_factory() as session:
        yield session
