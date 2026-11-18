"""chess.com public API client (https://www.chess.com/news/view/published-data-api).

chess.com asks API users to:
* identify themselves in the User-Agent (CHESSCOM_CONTACT),
* make requests one at a time (parallel requests get HTTP 429).
So requests go through a single-slot semaphore, 429s are retried with backoff,
and responses are cached in Redis: finished months never change, so they are
cached for a week; the current month for ten minutes.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from ..errors import AppError, NotFound, UpstreamError
from ..redis_client import redis

BASE = "https://api.chess.com/pub"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,25}$")
MONTH_RE = re.compile(r"^\d{4}/\d{2}$")

_slot = asyncio.Semaphore(1)
_client: httpx.AsyncClient | None = None


def validate_username(username: str) -> str:
    if not USERNAME_RE.fullmatch(username):
        raise AppError("That isn't a valid chess.com username.", code="invalid_username")
    return username.lower()


def init_client(contact: str) -> None:
    global _client
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0),
        headers={"User-Agent": f"ShahMaat/1.0 (contact: {contact})", "Accept": "application/json"},
        follow_redirects=True,
    )


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


async def _get(path: str, cache_key: str, ttl_s: int) -> Any:
    cached = await redis().get(cache_key)
    if cached is not None:
        return json.loads(cached)
    if _client is None:
        raise UpstreamError("chess.com client not initialised.")
    async with _slot:
        for attempt in range(3):
            try:
                resp = await _client.get(f"{BASE}{path}")
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise UpstreamError("chess.com is not responding. Try again soon.") from exc
                await asyncio.sleep(1 + attempt)
                continue
            if resp.status_code == 429:
                await asyncio.sleep(2**attempt)
                continue
            if resp.status_code in (404, 410):
                raise NotFound("chess.com has no such player or month.")
            if resp.status_code != 200:
                raise UpstreamError(f"chess.com answered with HTTP {resp.status_code}.")
            data = resp.json()
            await redis().set(cache_key, json.dumps(data), ex=ttl_s)
            return data
    raise UpstreamError("chess.com is busy. Try again in a minute.")


async def archives(username: str) -> list[str]:
    """Months with games, newest first, as 'YYYY/MM'."""
    user = validate_username(username)
    data = await _get(f"/player/{user}/games/archives", f"cc:archives:{user}", 3600)
    months = []
    for url in data.get("archives", []):
        tail = "/".join(str(url).rstrip("/").split("/")[-2:])
        if MONTH_RE.fullmatch(tail):
            months.append(tail)
    return list(reversed(months))


async def month_games(username: str, month: str) -> list[dict[str, Any]]:
    user = validate_username(username)
    if not MONTH_RE.fullmatch(month):
        raise AppError("Month must look like 2026/11.", code="bad_month")
    now = datetime.now(UTC)
    current = month == f"{now.year:04d}/{now.month:02d}"
    data = await _get(
        f"/player/{user}/games/{month}", f"cc:games:{user}:{month}", 600 if current else 7 * 86400
    )
    games = [g for g in data.get("games", []) if g.get("rules") == "chess" and g.get("pgn")]
    return list(reversed(games))  # newest first


def summarize(game: dict[str, Any]) -> dict[str, Any]:
    """The fields the import list shows. The full PGN stays server-side."""
    white, black = game.get("white", {}), game.get("black", {})
    return {
        "uuid": game.get("uuid"),
        "url": game.get("url"),
        "end_time": game.get("end_time"),
        "time_class": game.get("time_class"),
        "time_control": game.get("time_control"),
        "rated": game.get("rated"),
        "white": {
            "username": white.get("username"),
            "rating": white.get("rating"),
            "result": white.get("result"),
        },
        "black": {
            "username": black.get("username"),
            "rating": black.get("rating"),
            "result": black.get("result"),
        },
        "accuracies": game.get("accuracies"),
    }
