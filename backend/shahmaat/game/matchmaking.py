"""Rating-based matchmaking.

Each time control has a queue in Redis: a sorted set scored by rating. A waiting
player accepts opponents within a rating window that starts narrow (±BASE_WINDOW)
and widens the longer they wait (+GROWTH per second, up to MAX_WINDOW), so close
matches are preferred but nobody waits forever.

Pairing is one Lua script: find the closest opponent whose OWN window also
accepts us, remove both from the queue, return the opponent. Atomic, so two
servers can never hand the same player two opponents.

Cost-aware: the retry loop only runs while someone on THIS server is waiting.
An empty site makes zero Redis calls for matchmaking.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
import uuid
from dataclasses import dataclass
from typing import cast

import structlog

from ..chess_core.timecontrols import TimeControl, get_time_control
from ..db import session_scope
from ..db.models import Rating
from ..errors import AppError
from ..metrics import QUEUE_WAIT
from ..redis_client import redis, run_script
from .service import GameService

BASE_WINDOW = 75
GROWTH_PER_S = 25
MAX_WINDOW = 600
RETRY_EVERY_S = 1.5
log = structlog.get_logger("shahmaat.matchmaking")


def queue_key(tc: str) -> str:
    return f"mm:q:{tc}"


def meta_key(tc: str) -> str:
    return f"mm:meta:{tc}"


def user_queue_key(user_id: str) -> str:
    return f"mm:user:{user_id}"


def window_for(waited_ms: int) -> int:
    return int(min(MAX_WINDOW, BASE_WINDOW + GROWTH_PER_S * waited_ms / 1000))


@dataclass(slots=True)
class Waiting:
    tc: TimeControl
    rating: int
    joined_ms: int


class Matchmaker:
    def __init__(self, games: GameService) -> None:
        self._games = games
        self._local: dict[str, Waiting] = {}
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="matchmaker")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        for user_id in list(self._local):
            await self.leave(user_id)

    async def join(self, user_id: str, tc_key: str) -> dict[str, object]:
        tc = get_time_control(tc_key)
        if tc is None:
            raise AppError("Unknown time control.", code="bad_time_control")
        await self._games.ensure_free(user_id)
        await self.leave(user_id)  # switching time controls replaces the old ticket

        async with session_scope() as db:
            row = await db.get(Rating, (uuid.UUID(user_id), tc.time_class))
        rating = round(row.rating) if row else 1500
        now = int(time.time() * 1000)
        pipe = redis().pipeline(transaction=True)
        pipe.hset(meta_key(tc.key), user_id, f"{rating}|{now}")
        pipe.zadd(queue_key(tc.key), {user_id: rating})
        pipe.set(user_queue_key(user_id), tc.key, ex=3600)
        await pipe.execute()
        self._local[user_id] = Waiting(tc=tc, rating=rating, joined_ms=now)
        self._wake.set()
        await self._try_pair(user_id)
        return {"status": "searching", "tc": tc.key, "rating": rating}

    async def leave(self, user_id: str) -> None:
        waiting = self._local.pop(user_id, None)
        tc_key = waiting.tc.key if waiting else cast(str | None, await redis().get(user_queue_key(user_id)))
        if not tc_key:
            return
        pipe = redis().pipeline(transaction=True)
        pipe.zrem(queue_key(tc_key), user_id)
        pipe.hdel(meta_key(tc_key), user_id)
        pipe.delete(user_queue_key(user_id))
        await pipe.execute()

    def is_waiting(self, user_id: str) -> bool:
        return user_id in self._local

    async def _try_pair(self, user_id: str) -> bool:
        waiting = self._local.get(user_id)
        if waiting is None:
            return False
        now = int(time.time() * 1000)
        opponent = await run_script(
            "pair",
            [queue_key(waiting.tc.key), meta_key(waiting.tc.key)],
            [user_id, now, BASE_WINDOW, GROWTH_PER_S, MAX_WINDOW],
        )
        if opponent == "__gone__":  # another server already paired us
            self._local.pop(user_id, None)
            return False
        if not opponent:
            return False
        self._local.pop(user_id, None)
        self._local.pop(opponent, None)  # if the opponent is on this server too
        await redis().delete(user_queue_key(user_id), user_queue_key(opponent))
        QUEUE_WAIT.observe((now - waiting.joined_ms) / 1000)

        white, black = (user_id, opponent) if random.random() < 0.5 else (opponent, user_id)
        try:
            await self._games.create_game(white, black, waiting.tc, rated=True, source="queue")
        except Exception:
            log.exception("pairing_failed", a=user_id, b=opponent)
            for uid in (user_id, opponent):
                await self._games.notify_user(
                    uid,
                    {
                        "type": "queue.state",
                        "status": "idle",
                        "error": "Pairing failed, please search again.",
                    },
                )
        return True

    async def _loop(self) -> None:
        while True:
            if not self._local:
                self._wake.clear()
                await self._wake.wait()  # sleep (no Redis calls) until someone joins
            await asyncio.sleep(RETRY_EVERY_S)
            for user_id in list(self._local):
                try:
                    await self._try_pair(user_id)
                    waiting = self._local.get(user_id)
                    if waiting:
                        waited = int(time.time() * 1000) - waiting.joined_ms
                        await self._games.notify_user(
                            user_id,
                            {
                                "type": "queue.state",
                                "status": "searching",
                                "tc": waiting.tc.key,
                                "rating": waiting.rating,
                                "window": window_for(waited),
                                "waited_ms": waited,
                            },
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("matchmaking_retry_failed", user_id=user_id)
