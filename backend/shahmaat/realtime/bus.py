"""Message bus: how one server tells every interested connection about a change.

Two interchangeable implementations behind one interface:
* LocalBus  — in-process. Right for a single server: zero Redis commands per move.
* RedisBus  — Redis pub/sub. Needed when 2+ servers run behind a load balancer:
  a move made on server A must reach a spectator connected to server B.
Switched by MULTI_INSTANCE. The rest of the code can't tell the difference.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import structlog
from redis.asyncio import Redis

Handler = Callable[[str, dict[str, Any]], Awaitable[None]]
log = structlog.get_logger("shahmaat.bus")


class Bus(Protocol):
    async def publish(self, channel: str, message: dict[str, Any]) -> None: ...
    async def subscribe(self, channel: str) -> None: ...
    async def unsubscribe(self, channel: str) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class LocalBus:
    def __init__(self, handler: Handler) -> None:
        self._handler = handler

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        await self._handler(channel, message)

    async def subscribe(self, channel: str) -> None:
        return None

    async def unsubscribe(self, channel: str) -> None:
        return None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class RedisBus:
    """One pub/sub connection per server, subscribed to the channels local clients need.

    Subscriptions are reference-counted: ten spectators of one game on this server
    still mean one Redis subscription.
    """

    ALWAYS = ("timers",)

    def __init__(self, client: Redis, handler: Handler) -> None:
        self._client = client
        self._handler = handler
        self._pubsub = client.pubsub(ignore_subscribe_messages=True)
        self._refs: dict[str, int] = defaultdict(int)
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        await self._pubsub.subscribe(*self.ALWAYS)
        self._task = asyncio.create_task(self._listen(), name="redis-bus")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._pubsub.aclose()

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        await self._client.publish(channel, json.dumps(message))

    async def subscribe(self, channel: str) -> None:
        async with self._lock:
            self._refs[channel] += 1
            if self._refs[channel] == 1:
                await self._pubsub.subscribe(channel)

    async def unsubscribe(self, channel: str) -> None:
        async with self._lock:
            if self._refs.get(channel, 0) <= 0:
                return
            self._refs[channel] -= 1
            if self._refs[channel] == 0:
                del self._refs[channel]
                await self._pubsub.unsubscribe(channel)

    async def _listen(self) -> None:
        while True:
            try:
                async for msg in self._pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    try:
                        await self._handler(msg["channel"], json.loads(msg["data"]))
                    except Exception:
                        log.exception("bus_handler_failed", channel=msg.get("channel"))
            except asyncio.CancelledError:
                raise
            except Exception:
                # Connection dropped: wait, then resubscribe everything we had.
                log.warning("bus_reconnecting")
                await asyncio.sleep(1)
                with contextlib.suppress(Exception):
                    channels = [*self.ALWAYS, *self._refs.keys()]
                    await self._pubsub.subscribe(*channels)
