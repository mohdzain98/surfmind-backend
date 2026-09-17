"""
This module defines the primary application controller for the FastAPI backend.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from src.controller.core_controller import redis_client
from src.controller.core_controller import router as core_router
from src.controller.sync_controller import router as sync_router
from src.db.session import async_session_factory
from src.utility.logger import AppLogger
from src.utility.settings import settings

AppLogger.init(
    level=logging.DEBUG if settings.debug else logging.INFO,
    log_to_file=True,
)

logger = AppLogger.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Log Postgres/Redis reachability at startup instead of staying silent.

    Both clients connect lazily otherwise — the app would start and
    `/health` would report "ok" even with either fully unreachable, and
    the first sign of trouble would be a failed request. Doesn't block
    startup on a failed check: a dependency coming up slightly after the
    app shouldn't turn into a systemd restart loop.
    """
    try:
        async with async_session_factory() as db:
            await db.execute(text("SELECT 1"))
        logger.info("Postgres connected")
    except Exception as exc:
        logger.error(f"Postgres connection failed at startup: {exc}")

    try:
        await asyncio.to_thread(redis_client.ping)
        logger.info("Redis connected")
    except Exception as exc:
        logger.error(f"Redis connection failed at startup: {exc}")

    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(core_router)
app.include_router(sync_router)


@app.get("/", tags=["Health"])
def health_check():
    """Simple root health endpoint confirming setup."""
    return {"status": "ok", "message": "Setup Successfull"}


@app.get("/health", tags=["Health"])
def health_check():
    """Secondary health endpoint to monitor FastAPI server state."""
    return {"status": "ok", "message": "Surfmind FastAPI server running!"}
