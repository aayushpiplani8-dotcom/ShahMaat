"""Live games in Redis, updated with optimistic locking (compare-and-set).

Each game is a Redis hash with two fields: `state` (JSON) and `v` (a version
number). To change a game you read it, compute the new state, and save it ONLY
if `v` is still what you read — checked and written by one atomic Lua script.
If another request changed the game in between, the save is refused and the
change is recomputed from fresh state. No locks are held while thinking, so a
slow request can never block a fast one, and two servers can't both win.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import cast

from ..errors import Conflict, NotFound
from ..metrics import CAS_CONFLICTS
from ..redis_client import redis, run_script
from .state import LiveGame

LIVE_SET = "games:live"
ENDED_TTL_S = 60 * 60  # finished games stay readable in Redis for an hour (late joiners, rematch)
MAX_RETRIES = 8


def game_key(game_id: str) -> str:
    return f"game:{game_id}"


def user_game_key(user_id: str) -> str:
    return f"user:{user_id}:game"


async def load(game_id: str) -> tuple[LiveGame, int] | None:
    raw = await redis().hgetall(game_key(game_id))
    if not raw or "state" not in raw:
        return None
    return LiveGame.from_json_dict(json.loads(raw["state"])), int(raw.get("v", "0"))


async def create(game: LiveGame) -> None:
    pipe = redis().pipeline(transaction=True)
    pipe.hset(game_key(game.id), mapping={"v": "1", "state": json.dumps(game.to_json_dict())})
    pipe.sadd(LIVE_SET, game.id)
    pipe.set(user_game_key(game.white.id), game.id)
    pipe.set(user_game_key(game.black.id), game.id)
    await pipe.execute()


async def save_if_unchanged(game: LiveGame, expected_version: int) -> bool:
    ttl = ENDED_TTL_S if game.status == "ended" else 0
    ok = await run_script(
        "cas_game",
        [game_key(game.id)],
        [str(expected_version), str(expected_version + 1), json.dumps(game.to_json_dict()), ttl],
    )
    return bool(int(ok))


class NoChange(Exception):  # noqa: N818 — a signal, not an error
    """Raised inside a `change` function to say "nothing to save"."""


async def mutate[T](game_id: str, change: Callable[[LiveGame], T]) -> tuple[LiveGame, int, T | None, bool]:
    """Applies `change` to the latest state and saves it atomically, retrying on conflicts.

    `change` edits the game in place. It may raise an AppError (e.g. IllegalAction)
    to refuse, or NoChange to skip saving. It must not have side effects outside
    the game object, because it can run several times if other requests race it.

    Returns (game, version, what `change` returned, whether anything was saved).
    """
    for _ in range(MAX_RETRIES):
        loaded = await load(game_id)
        if loaded is None:
            raise NotFound("Game not found.")
        game, version = loaded
        try:
            result = change(game)
        except NoChange:
            return game, version, None, False
        if await save_if_unchanged(game, version):
            return game, version + 1, result, True
        CAS_CONFLICTS.inc()
    raise Conflict("The game is busy, please retry.", code="busy")


async def finish_bookkeeping(game: LiveGame) -> None:
    """Once a game has ended: it's no longer live, and the players are free to play again."""
    pipe = redis().pipeline(transaction=False)
    pipe.srem(LIVE_SET, game.id)
    for uid in (game.white.id, game.black.id):
        # Only clear the pointer if it still points at THIS game (a rematch may have replaced it).
        pipe.eval(
            "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0",
            1,
            user_game_key(uid),
            game.id,
        )
    await pipe.execute()


async def active_game_of(user_id: str) -> str | None:
    return cast(str | None, await redis().get(user_game_key(user_id)))


async def live_ids(limit: int = 200) -> list[str]:
    ids = cast(list[str] | None, await redis().srandmember(LIVE_SET, limit))
    return list(ids or [])
