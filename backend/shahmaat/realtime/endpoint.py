"""The /ws endpoint: one WebSocket per browser tab.

Lifecycle
1. Handshake: the Origin header must be our own site (blocks other websites from
   opening sockets with a visitor's browser), and each IP gets a connection cap.
2. The first message must be {"type": "auth", "token": ...} within 5 seconds.
   (The token goes in a message, not the URL, so it never lands in proxy logs.)
   A null token makes a watch-only guest connection.
3. Every 10 s the server pings; the round-trip time is used for lag compensation.
4. Messages are size-capped, rate-limited per connection and schema-validated.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import cast

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..auth.tokens import decode_access_token
from ..config import get_settings
from ..errors import AppError
from ..game import store
from ..game.service import user_channel
from ..game.state import Color
from ..redis_client import redis
from ..runtime import Runtime
from . import protocol as p
from .hub import Connection

router = APIRouter()
log = structlog.get_logger("shahmaat.ws")

AUTH_TIMEOUT_S = 5
PING_EVERY_S = 10
PRESENCE_TTL_S = 24 * 3600


def _now_ms() -> int:
    return int(time.time() * 1000)


def _origin_allowed(origin: str | None) -> bool:
    settings = get_settings()
    if origin is None:
        return not settings.is_production  # non-browser tools in development / tests
    allowed = {settings.app_origin}
    if not settings.is_production:
        allowed |= {"http://localhost:5173", "http://127.0.0.1:5173", f"http://localhost:{settings.port}"}
    return origin.rstrip("/") in allowed


def _client_ip(ws: WebSocket) -> str:
    settings = get_settings()
    if settings.trust_proxy:
        forwarded = ws.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return ws.client.host if ws.client else "unknown"


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    rt = cast(Runtime, ws.app.state.rt)
    if not _origin_allowed(ws.headers.get("origin")):
        await ws.close(code=4003, reason="origin not allowed")
        return
    ip = _client_ip(ws)
    if not rt.hub.admit(ip):
        await ws.close(code=4029, reason="too many connections")
        return

    conn = Connection(ws, ip)
    pinger: asyncio.Task[None] | None = None
    try:
        await ws.accept()
        conn.start()
        if not await _authenticate(rt, conn):
            return
        pinger = asyncio.create_task(_ping_loop(conn))
        await _read_loop(rt, conn)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws_crashed", user=conn.user_id)
    finally:
        if pinger:
            pinger.cancel()
        await _cleanup(rt, conn)
        rt.hub.release(ip)


async def _authenticate(rt: Runtime, conn: Connection) -> bool:
    try:
        raw = await asyncio.wait_for(conn.ws.receive_text(), timeout=AUTH_TIMEOUT_S)
        msg = p.client_message.validate_json(raw)
        if not isinstance(msg, p.Auth):
            raise AppError("Authenticate first.")
        if msg.token:
            conn.user = decode_access_token(rt.settings, msg.token)
    except (TimeoutError, ValidationError, AppError) as exc:
        code = getattr(exc, "code", "auth_failed")
        conn.send({"type": "error", "code": code, "message": "Authentication failed."})
        await asyncio.sleep(0.05)  # let the writer flush the error
        await conn.ws.close(code=4001, reason="auth failed")
        return False

    hello: dict[str, object] = {
        "type": "hello",
        "server_now_ms": _now_ms(),
        "user": None,
        "active_game": None,
    }
    if conn.user:
        await rt.hub.join(conn, user_channel(str(conn.user.user_id)))
        hello["user"] = {"id": str(conn.user.user_id), "username": conn.user.username}
        game_id = await store.active_game_of(str(conn.user.user_id))
        if game_id:
            loaded = await store.load(game_id)
            if loaded and loaded[0].status == "active":
                hello["active_game"] = game_id
        hello["searching"] = rt.matchmaker.is_waiting(str(conn.user.user_id))
    conn.send(hello)
    return True


async def _ping_loop(conn: Connection) -> None:
    while not conn.closed:
        await asyncio.sleep(PING_EVERY_S)
        conn.send({"type": "ping", "t": _now_ms()})


async def _read_loop(rt: Runtime, conn: Connection) -> None:
    while not conn.closed:
        raw = await conn.ws.receive_text()
        if len(raw.encode()) > p.MAX_MESSAGE_BYTES:
            await conn.ws.close(code=4009, reason="message too large")
            return
        if not conn.bucket.take():
            conn.send({"type": "error", "code": "rate_limited", "message": "Slow down."})
            continue
        try:
            msg = p.client_message.validate_json(raw)
        except ValidationError:
            conn.send({"type": "error", "code": "bad_message", "message": "Malformed message."})
            continue
        try:
            await _dispatch(rt, conn, msg)
        except AppError as exc:
            conn.send({"type": "error", **exc.to_dict(), "ref": msg.ref})
        except Exception:
            log.exception("ws_handler_failed", type=msg.type, user=conn.user_id)
            conn.send(
                {
                    "type": "error",
                    "code": "internal_error",
                    "message": "Something went wrong.",
                    "ref": msg.ref,
                }
            )


def _require_user(conn: Connection) -> str:
    if conn.user_id is None:
        raise AppError("Sign in to play.", code="unauthorized", status=401)
    return conn.user_id


async def _dispatch(rt: Runtime, conn: Connection, msg: p.ClientMessage) -> None:
    games = rt.games
    match msg:
        case p.Pong(t=t):
            conn.rtt_ms = max(0, min(5000, _now_ms() - t))
        case p.QueueJoin(tc=tc):
            state = await rt.matchmaker.join(_require_user(conn), tc)
            conn.send({"type": "queue.state", **state})
        case p.QueueLeave():
            await rt.matchmaker.leave(_require_user(conn))
            conn.send({"type": "queue.state", "status": "idle"})
        case p.Watch(game_id=game_id):
            await _watch(rt, conn, game_id)
        case p.Unwatch(game_id=game_id):
            await _unwatch(rt, conn, game_id)
        case p.Move(game_id=game_id, uci=uci, ply=ply):
            await games.move(_require_user(conn), game_id, uci, ply, lag_ms=conn.rtt_ms // 2)
        case p.Action(game_id=game_id, action=action):
            uid = _require_user(conn)
            if action == "resign":
                await games.resign(uid, game_id)
            elif action == "abort":
                await games.abort(uid, game_id)
            elif action == "offer_draw":
                await games.offer_draw(uid, game_id)
            elif action in ("accept_draw", "decline_draw"):
                await games.answer_draw(uid, game_id, accept=action == "accept_draw")
            elif action == "claim_win":
                await games.claim_win(uid, game_id)
            elif action == "rematch":
                await games.offer_rematch(uid, game_id)
            elif action == "decline_rematch":
                await games.decline_rematch(uid, game_id)
        case p.Auth():
            raise AppError("Already authenticated.")


async def _watch(rt: Runtime, conn: Connection, game_id: str) -> None:
    snapshot = await rt.games.snapshot(game_id)
    if snapshot is None:
        conn.send(
            {"type": "game.gone", "game_id": game_id}
        )  # finished long ago: the client loads it over REST
        return
    channel = f"game:{game_id}"
    await rt.hub.join(conn, channel)
    conn.send({"type": "game.state", "game": snapshot, "watchers": rt.hub.watchers(channel)})

    uid = conn.user_id
    if uid and snapshot["status"] == "active" and game_id not in conn.player_games:
        color: Color | None = (
            "white" if snapshot["white"]["id"] == uid else "black" if snapshot["black"]["id"] == uid else None
        )
        if color:
            conn.player_games[game_id] = color
            count = await _presence_add(game_id, color, 1)
            if count == 1:
                await rt.games.set_presence(game_id, color, online=True)


async def _unwatch(rt: Runtime, conn: Connection, game_id: str) -> None:
    await rt.hub.leave(conn, f"game:{game_id}")
    color = conn.player_games.pop(game_id, None)
    if color:
        await _player_left(rt, game_id, color)  # type: ignore[arg-type]


async def _player_left(rt: Runtime, game_id: str, color: Color) -> None:
    count = await _presence_add(game_id, color, -1)
    if count <= 0:
        await rt.games.set_presence(game_id, color, online=False)


async def _presence_add(game_id: str, color: str, delta: int) -> int:
    """Counts a player's open tabs across all servers. 0 means they've really gone."""
    key = f"presence:{game_id}"
    pipe = redis().pipeline(transaction=True)
    pipe.hincrby(key, color, delta)
    pipe.expire(key, PRESENCE_TTL_S)
    count, _ = await pipe.execute()
    if count < 0:
        await redis().hset(key, color, 0)
        count = 0
    return int(count)


async def _cleanup(rt: Runtime, conn: Connection) -> None:
    with contextlib.suppress(Exception):
        for game_id, color in list(conn.player_games.items()):
            await _player_left(rt, game_id, color)  # type: ignore[arg-type]
        conn.player_games.clear()
        # Last tab closed while searching: leave the queue so nobody gets paired with a ghost.
        if (
            conn.user_id
            and rt.matchmaker.is_waiting(conn.user_id)
            and not rt.hub.user_connected_elsewhere(conn)
        ):
            await rt.matchmaker.leave(conn.user_id)
        await rt.hub.leave_all(conn)
    await conn.stop()
