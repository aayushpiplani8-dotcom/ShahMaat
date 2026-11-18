"""Games: live list, game details, PGN export, time controls and private challenges."""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.deps import CurrentUser
from ..chess_core.rules import to_pgn
from ..chess_core.timecontrols import TIME_CONTROLS
from ..db import get_session
from ..errors import NotFound
from ..game import challenges, store
from ..game.lookup import load_archived
from ..game.service import now_ms
from ..runtime import Runtime
from ..security import ratelimit

router = APIRouter(prefix="/api", tags=["games"])
DB = Annotated[AsyncSession, Depends(get_session)]


def rt_of(request: Request) -> Runtime:
    return cast(Runtime, request.app.state.rt)


@router.get("/time-controls")
async def time_controls() -> list[dict[str, object]]:
    return [tc.to_dict() for tc in TIME_CONTROLS.values()]


@router.get("/games/live")
async def live_games() -> list[dict[str, Any]]:
    """Up to 30 games being played right now, for the 'Watch' page."""
    out = []
    now = now_ms()
    for game_id in await store.live_ids(60):
        loaded = await store.load(game_id)
        if loaded is None or loaded[0].status != "active":
            continue
        g, v = loaded
        snap = g.snapshot(now, v)
        out.append(
            {
                "id": g.id,
                "white": snap["white"],
                "black": snap["black"],
                "tc": snap["tc"],
                "fen": g.fen,
                "ply": g.ply,
                "rated": g.rated,
                "last_move": g.moves[-1] if g.moves else None,
            }
        )
        if len(out) >= 30:
            break
    out.sort(key=lambda x: -(x["white"]["rating"] + x["black"]["rating"]))
    return out


@router.get("/games/{game_id}")
async def get_game(game_id: str, request: Request, db: DB) -> dict[str, Any]:
    if len(game_id) > 12:
        raise NotFound("Game not found.")
    snapshot = await rt_of(request).games.snapshot(game_id)
    if snapshot is not None and not (snapshot["status"] == "ended" and snapshot.get("result") == "*"):
        return {"live": snapshot["status"] == "active", "game": snapshot}
    archived = await load_archived(db, game_id)
    if archived is None:
        if snapshot is not None:  # aborted game, still in Redis for a while
            return {"live": False, "game": snapshot}
        raise NotFound("Game not found.")
    return {"live": False, "game": archived}


@router.get("/games/{game_id}/pgn", response_class=PlainTextResponse)
async def game_pgn(game_id: str, db: DB) -> str:
    game = await load_archived(db, game_id)
    if game is None:
        raise NotFound("Game not found (games in progress can't be exported yet).")
    headers = {
        "Event": f"ShahMaat {'rated' if game['rated'] else 'casual'} {game['tc']['time_class']} game",
        "Site": "ShahMaat",
        "Date": game["ended_at"][:10].replace("-", "."),
        "White": game["white"]["username"],
        "Black": game["black"]["username"],
        "Result": game["result"],
        "WhiteElo": str(game["white"]["rating"]),
        "BlackElo": str(game["black"]["rating"]),
        "TimeControl": f"{game['tc']['initial_ms'] // 1000}+{game['tc']['increment_ms'] // 1000}",
        "Termination": game["termination"],
    }
    if game["opening"]:
        headers["ECO"] = game["opening"]["eco"]
        headers["Opening"] = game["opening"]["name"]
    return to_pgn(game["moves"], headers, clocks_ms=game["clocks_ms"])


# ------------------------------------------------------------------ challenges
class ChallengeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tc: str = Field(max_length=8)
    color: Literal["white", "black", "random"] = "random"
    rated: bool = False


@router.post("/challenges")
async def create_challenge(body: ChallengeIn, user: CurrentUser, request: Request) -> dict[str, Any]:
    await ratelimit.hit(f"challenge:{user.user_id}", limit=20, window_s=3600)
    return await challenges.create(
        rt_of(request).games,
        user_id=str(user.user_id),
        username=user.username,
        tc_key=body.tc,
        color=body.color,
        rated=body.rated,
    )


@router.get("/challenges/{code}")
async def get_challenge(code: str) -> dict[str, Any]:
    return await challenges.get(code[:32])


@router.post("/challenges/{code}/accept")
async def accept_challenge(code: str, user: CurrentUser, request: Request) -> dict[str, str]:
    game_id = await challenges.accept(rt_of(request).games, code[:32], str(user.user_id))
    return {"game_id": game_id}


@router.delete("/challenges/{code}")
async def cancel_challenge(code: str, user: CurrentUser) -> dict[str, bool]:
    await challenges.cancel(code[:32], str(user.user_id))
    return {"ok": True}
