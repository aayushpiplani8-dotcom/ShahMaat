"""Tracks this server's WebSocket connections and routes bus messages to them.

Each connection has its own outbound queue and writer task. Broadcasting a move
only drops the message into each queue (instant); a slow or stalled browser can
never hold up the move for everyone else. If a client's queue overflows, that
client is disconnected (it will reconnect and get a fresh snapshot).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import WebSocket

from ..auth.tokens import AccessClaims
from ..metrics import WS_CONNECTIONS
from ..security.ratelimit import TokenBucket

if TYPE_CHECKING:
    from ..game.timers import TimerScheduler
    from .bus import Bus

log = structlog.get_logger("shahmaat.ws")
OUTBOUND_QUEUE = 64
MAX_CONNECTIONS_PER_IP = 20


class Connection:
    def __init__(self, ws: WebSocket, ip: str) -> None:
        self.ws = ws
        self.ip = ip
        self.user: AccessClaims | None = None
        self.channels: set[str] = set()
        self.player_games: dict[str, str] = {}  # game id -> our colour, for presence
        self.rtt_ms = 0
        self.bucket = TokenBucket(capacity=20, rate=6)  # bursts of 20, then 6 msg/s
        self._out: asyncio.Queue[str | None] = asyncio.Queue(maxsize=OUTBOUND_QUEUE)
        self._writer: asyncio.Task[None] | None = None
        self.closed = False

    @property
    def user_id(self) -> str | None:
        return str(self.user.user_id) if self.user else None

    def start(self) -> None:
        self._writer = asyncio.create_task(self._write_loop())

    def send(self, message: dict[str, Any]) -> None:
        if self.closed:
            return
        try:
            self._out.put_nowait(json.dumps(message, separators=(",", ":")))
        except asyncio.QueueFull:
            log.warning("ws_slow_consumer", ip=self.ip, user=self.user_id)
            self.closed = True
            with contextlib.suppress(asyncio.QueueFull):
                self._out.put_nowait(None)

    async def _write_loop(self) -> None:
        try:
            while True:
                item = await self._out.get()
                if item is None:
                    await self.ws.close(code=4008, reason="too slow")
                    return
                await self.ws.send_text(item)
        except Exception:
            self.closed = True  # socket gone; the reader notices and cleans up

    async def stop(self) -> None:
        self.closed = True
        if self._writer:
            self._writer.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._writer


class Hub:
    def __init__(self) -> None:
        self.bus: Bus | None = None
        self.timers: TimerScheduler | None = None
        self._by_channel: dict[str, set[Connection]] = defaultdict(set)
        self._per_ip: dict[str, int] = defaultdict(int)
        self.started_at = time.time()

    # ------------------------------------------------------------ connections
    def admit(self, ip: str) -> bool:
        if self._per_ip[ip] >= MAX_CONNECTIONS_PER_IP:
            return False
        self._per_ip[ip] += 1
        WS_CONNECTIONS.inc()
        return True

    def release(self, ip: str) -> None:
        self._per_ip[ip] -= 1
        if self._per_ip[ip] <= 0:
            self._per_ip.pop(ip, None)
        WS_CONNECTIONS.dec()

    async def join(self, conn: Connection, channel: str) -> None:
        if channel in conn.channels:
            return
        conn.channels.add(channel)
        first = not self._by_channel[channel]
        self._by_channel[channel].add(conn)
        if first and self.bus:
            await self.bus.subscribe(channel)

    async def leave(self, conn: Connection, channel: str) -> None:
        if channel not in conn.channels:
            return
        conn.channels.discard(channel)
        members = self._by_channel.get(channel)
        if members is None:
            return
        members.discard(conn)
        if not members:
            del self._by_channel[channel]
            if self.bus:
                await self.bus.unsubscribe(channel)

    async def leave_all(self, conn: Connection) -> None:
        for channel in list(conn.channels):
            await self.leave(conn, channel)

    def user_connected_elsewhere(self, conn: Connection) -> bool:
        if not conn.user_id:
            return False
        return any(c is not conn for c in self._by_channel.get(f"user:{conn.user_id}", ()))

    def watchers(self, channel: str) -> int:
        return len(self._by_channel.get(channel, ()))

    # --------------------------------------------------------------- delivery
    async def deliver(self, channel: str, message: dict[str, Any]) -> None:
        """Bus handler: fan a message out to every local connection on the channel."""
        if channel == "timers":
            if self.timers is not None:
                self.timers.arm_local(message["game_id"], message.get("deadline"))
            return
        if channel.startswith("game:") and message.get("type") == "game.state":
            message = {**message, "watchers": self.watchers(channel)}
        for conn in list(self._by_channel.get(channel, ())):
            conn.send(message)
