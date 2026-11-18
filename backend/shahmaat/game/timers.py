"""Game deadlines (flag falls, first-move aborts) that survive restarts.

Three layers:
1. Redis sorted set `timers` (member = game id, score = deadline in ms). This is
   the durable truth: if the server restarts, nothing is forgotten.
2. An in-memory asyncio timer per game on every server, so a flag falls within
   milliseconds of the deadline — no polling Redis every 100 ms.
3. A slow sweeper (every SWEEP_S seconds) that asks Redis for overdue games, in
   case a local timer was lost (crash, missed pub/sub message).

Firing twice is harmless: the referee re-checks the game under compare-and-set,
so only one "game over" can ever be saved.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import cast

import structlog

from ..redis_client import redis

TIMERS_KEY = "timers"
SWEEP_S = 60
log = structlog.get_logger("shahmaat.timers")


def now_ms() -> int:
    return int(time.time() * 1000)


class TimerScheduler:
    def __init__(self, on_due: Callable[[str], Awaitable[None]]) -> None:
        self._on_due = on_due
        self._handles: dict[str, asyncio.TimerHandle] = {}
        self._sweeper: asyncio.Task[None] | None = None
        self._inflight: set[asyncio.Task[None]] = set()
        self.publish_hook: Callable[[str, int | None], Awaitable[None]] | None = None

    async def start(self) -> None:
        # Re-arm everything that was pending before a restart.
        pending = cast(list[tuple[str, float]], await redis().zrange(TIMERS_KEY, 0, -1, withscores=True))
        for game_id, score in pending:
            self.arm_local(game_id, int(score))
        self._sweeper = asyncio.create_task(self._sweep_forever(), name="timer-sweeper")

    async def stop(self) -> None:
        if self._sweeper:
            self._sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweeper
        for handle in self._handles.values():
            handle.cancel()
        self._handles.clear()
        for task in list(self._inflight):
            task.cancel()

    async def set(self, game_id: str, deadline_ms: int | None) -> None:
        """Records the game's next deadline (None clears it) durably and locally."""
        if deadline_ms is None:
            await redis().zrem(TIMERS_KEY, game_id)
        else:
            await redis().zadd(TIMERS_KEY, {game_id: deadline_ms})
        self.arm_local(game_id, deadline_ms)
        if self.publish_hook:  # tell other servers (multi-instance mode)
            await self.publish_hook(game_id, deadline_ms)

    def arm_local(self, game_id: str, deadline_ms: int | None) -> None:
        old = self._handles.pop(game_id, None)
        if old:
            old.cancel()
        if deadline_ms is None:
            return
        loop = asyncio.get_running_loop()
        delay = max(0.0, (deadline_ms - now_ms()) / 1000) + 0.005  # tiny margin so 'now >= deadline' holds
        self._handles[game_id] = loop.call_later(delay, self._fire, game_id)

    def _fire(self, game_id: str) -> None:
        self._handles.pop(game_id, None)
        task = asyncio.create_task(self._run(game_id))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _run(self, game_id: str) -> None:
        try:
            await self._on_due(game_id)
        except Exception:
            log.exception("timer_failed", game_id=game_id)

    async def _sweep_forever(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_S)
            try:
                overdue = cast(list[str], await redis().zrangebyscore(TIMERS_KEY, "-inf", now_ms() - 1000))
                for game_id in overdue:
                    await self._run(game_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("timer_sweep_failed")
