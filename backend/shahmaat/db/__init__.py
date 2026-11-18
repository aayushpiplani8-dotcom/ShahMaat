"""Database connection.

One async engine per process with a small connection pool. Each request (or
background job) borrows a session for a short unit of work and gives it back.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_db(url: str, *, pool_size: int = 5) -> AsyncEngine:
    global _engine, _sessionmaker
    _engine = create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=5,
        pool_pre_ping=True,  # free-tier databases sleep; reconnect instead of failing the first query
        pool_recycle=300,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def close_db() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database not initialised")
    return _engine


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A session that commits on success and rolls back on any error."""
    if _sessionmaker is None:
        raise RuntimeError("Database not initialised")
    async with _sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with session_scope() as session:
        yield session
