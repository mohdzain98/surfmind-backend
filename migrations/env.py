"""Alembic environment for SurfMind's async Postgres schema.

Runs migrations against the same `DATABASE_URL` the app uses (via
`SecretsProvider`), driving the async engine synchronously through
`run_sync` as recommended for SQLAlchemy 2.0 async setups.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import src.db.models  # noqa: F401 — registers models on Base.metadata
from src.db.base import Base
from src.utility.provider import SecretsProvider

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit migration SQL without a live DB connection."""
    context.configure(
        url=SecretsProvider.get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live DB connection via the async engine."""
    engine = create_async_engine(SecretsProvider.get_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
