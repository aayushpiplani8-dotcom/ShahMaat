"""Test setup: real Postgres and real Redis (no mocks for the things that matter).

Set TEST_DATABASE_URL / TEST_REDIS_URL to point at disposable databases. Every
test starts from empty tables and an empty Redis database.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://shahmaat:shahmaat@localhost:5432/shahmaat_test")
TEST_REDIS = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")

os.environ.update(
    {
        "ENV": "test",
        "DATABASE_URL": TEST_DB,
        "REDIS_URL": TEST_REDIS,
        "JWT_SECRET": "test-jwt-secret-0123456789abcdefghijklmnop",
        "REFRESH_TOKEN_SECRET": "test-refresh-secret-0123456789abcdefghijk",
        "APP_ORIGIN": "http://testserver",
        "CHESSCOM_CONTACT": "tests@example.com",
        "LOG_LEVEL": "WARNING",
        "MULTI_INSTANCE": "false",
    }
)

from shahmaat.config import Settings, get_settings  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
ORIGIN = {"origin": "http://testserver"}


def pytest_sessionstart(session: pytest.Session) -> None:
    """Fresh schema once per run, built by the real migrations (so they're tested too)."""
    env = {**os.environ, "DATABASE_URL": TEST_DB}
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=BACKEND,
        env=env,
        check=False,
        capture_output=True,
    )
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True)


async def _reset() -> None:
    import asyncpg
    from redis.asyncio import Redis

    conn = await asyncpg.connect(TEST_DB.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        await conn.execute(
            "TRUNCATE users, ratings, sessions, games, imported_games, reviews, puzzles RESTART IDENTITY CASCADE"
        )
    finally:
        await conn.close()
    r = Redis.from_url(TEST_REDIS)
    await r.flushdb()
    await r.aclose()


@pytest.fixture(autouse=True)
def clean_state() -> None:
    asyncio.run(_reset())


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def client(settings: Settings) -> Iterator:
    from fastapi.testclient import TestClient

    from shahmaat.main import create_app

    with TestClient(create_app(settings)) as c:
        yield c


@pytest_asyncio.fixture
async def rt(settings: Settings) -> AsyncIterator:
    """The game runtime without HTTP, for service-level tests (races, timers, restarts)."""
    from shahmaat import db
    from shahmaat.redis_client import close_redis, init_redis
    from shahmaat.runtime import build_runtime

    db.init_db(settings.database_url)
    await init_redis(settings.redis_url)
    runtime = build_runtime(settings)
    await runtime.start()
    yield runtime
    await runtime.stop()
    await close_redis()
    await db.close_db()


async def make_user(name: str, password: str = "password123") -> str:
    from shahmaat.auth.passwords import hash_password
    from shahmaat.auth.users import create_user
    from shahmaat.db import session_scope

    async with session_scope() as s:
        user = await create_user(s, name, password_hash=await hash_password(password))
        return str(user.id)


def register(client, name: str, password: str = "password123") -> dict:
    resp = client.post("/api/auth/register", json={"username": name, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()
