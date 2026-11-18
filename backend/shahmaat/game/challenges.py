"""Private challenges: "play me" links you send to a friend.

A challenge is a small JSON blob in Redis that expires by itself after 30
minutes, so abandoned links clean themselves up. Accepting uses GETDEL, which
reads and deletes in one atomic step: if two people open the link at the same
moment, only one of them gets the game.
"""

from __future__ import annotations

import json
import random
import secrets
from typing import Any, Literal

from ..chess_core.timecontrols import get_time_control
from ..errors import AppError, IllegalAction, NotFound
from ..redis_client import redis
from .service import GameService

TTL_S = 30 * 60
ColorChoice = Literal["white", "black", "random"]


def _key(code: str) -> str:
    return f"challenge:{code}"


async def create(
    games: GameService, *, user_id: str, username: str, tc_key: str, color: ColorChoice, rated: bool
) -> dict[str, Any]:
    tc = get_time_control(tc_key)
    if tc is None:
        raise AppError("Unknown time control.", code="bad_time_control")
    await games.ensure_free(user_id)
    code = secrets.token_urlsafe(9)
    data = {
        "code": code,
        "creator_id": user_id,
        "creator": username,
        "tc": tc.to_dict(),
        "color": color,
        "rated": rated,
    }
    await redis().set(_key(code), json.dumps(data), ex=TTL_S)
    return data


async def get(code: str) -> dict[str, Any]:
    raw = await redis().get(_key(code))
    if raw is None:
        raise NotFound("This challenge has expired or was already accepted.")
    data: dict[str, Any] = json.loads(raw)
    return data


async def cancel(code: str, user_id: str) -> None:
    data = await get(code)
    if data["creator_id"] != user_id:
        raise NotFound("Challenge not found.")
    await redis().delete(_key(code))


async def accept(games: GameService, code: str, user_id: str) -> str:
    data = await get(code)
    if data["creator_id"] == user_id:
        raise IllegalAction("You can't accept your own challenge.")
    await games.ensure_free(user_id)
    await games.ensure_free(data["creator_id"])
    raw = await redis().getdel(_key(code))  # atomic: only one accepter wins
    if raw is None:
        raise NotFound("This challenge was just accepted by someone else.")
    tc = get_time_control(data["tc"]["key"])
    assert tc is not None
    creator_white = {"white": True, "black": False}.get(data["color"], random.random() < 0.5)
    white, black = (data["creator_id"], user_id) if creator_white else (user_id, data["creator_id"])
    game = await games.create_game(white, black, tc, rated=bool(data["rated"]), source="challenge")
    return game.id
