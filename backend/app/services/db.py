import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    url = settings.database_url

    # SQLite needs check_same_thread disabled; Postgres has no such flag
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}

    engine = create_async_engine(url, connect_args=connect_args, echo=False)
    logger.info("Async DB engine created — scheme: %s", url.split(":")[0])
    return engine


@lru_cache
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that yields a session, commits on success, rolls back on error."""
    async with _session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an AsyncSession. Override in tests via dependency_overrides."""
    async with _session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
