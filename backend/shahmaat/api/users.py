"""Profiles, game history (keyset pagination), rating history, leaderboard, account settings."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..auth.deps import CurrentUser
from ..auth.users import by_id, by_username, ratings_for
from ..chess_core.glicko2 import is_provisional
from ..db import get_session
from ..db.models import Game, Rating, User
from ..errors import AppError, NotFound
from ..redis_client import redis
from ..services.chesscom import validate_username as validate_chesscom

router = APIRouter(prefix="/api", tags=["users"])
DB = Annotated[AsyncSession, Depends(get_session)]
TimeClassParam = Literal["bullet", "blitz", "rapid"]


def _encode_cursor(ended_at: datetime, game_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([ended_at.isoformat(), game_id]).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        ended, gid = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(ended), str(gid)
    except (ValueError, TypeError) as exc:
        raise AppError("Bad cursor.") from exc


@router.get("/users/{username}")
async def profile(username: str, db: DB) -> dict[str, Any]:
    user = await by_username(db, username[:20])
    if user is None:
        raise NotFound("No such player.")
    return {
        "id": str(user.id),
        "username": user.username,
        "joined": user.created_at.isoformat(),
        "chesscom_username": user.chesscom_username,
        "ratings": await ratings_for(db, user.id),
    }


@router.get("/users/{username}/games")
async def user_games(
    username: str,
    db: DB,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict[str, Any]:
    """Newest first. Keyset pagination: "games older than (ended_at, id)" stays fast on page 500,
    unlike OFFSET which re-scans every skipped row."""
    user = await by_username(db, username[:20])
    if user is None:
        raise NotFound("No such player.")
    w, b = aliased(User), aliased(User)
    q = (
        select(Game, w, b)
        .join(w, w.id == Game.white_id)
        .join(b, b.id == Game.black_id)
        .where(or_(Game.white_id == user.id, Game.black_id == user.id))
    )
    if cursor:
        c_ended, c_id = _decode_cursor(cursor)
        q = q.where(or_(Game.ended_at < c_ended, and_(Game.ended_at == c_ended, Game.id < c_id)))
    rows = (await db.execute(q.order_by(Game.ended_at.desc(), Game.id.desc()).limit(limit + 1))).all()
    items = []
    for game, white, black in rows[:limit]:
        items.append(
            {
                "id": game.id,
                "white": {"username": white.username, "rating": game.white_rating, "delta": game.white_delta},
                "black": {"username": black.username, "rating": game.black_rating, "delta": game.black_delta},
                "time_class": game.time_class,
                "initial_ms": game.initial_ms,
                "increment_ms": game.increment_ms,
                "rated": game.rated,
                "result": game.result,
                "termination": game.termination,
                "opening": game.opening_name,
                "moves": len(game.moves.split()) if game.moves else 0,
                "ended_at": game.ended_at.isoformat(),
            }
        )
    next_cursor = (
        _encode_cursor(rows[limit - 1][0].ended_at, rows[limit - 1][0].id) if len(rows) > limit else None
    )
    return {"items": items, "next_cursor": next_cursor}


@router.get("/users/{username}/rating-history")
async def rating_history(username: str, tc: TimeClassParam, db: DB) -> list[dict[str, Any]]:
    user = await by_username(db, username[:20])
    if user is None:
        raise NotFound("No such player.")
    rows = (
        await db.execute(
            select(
                Game.ended_at,
                Game.white_id,
                Game.white_rating,
                Game.white_delta,
                Game.black_rating,
                Game.black_delta,
            )
            .where(
                or_(Game.white_id == user.id, Game.black_id == user.id),
                Game.time_class == tc,
                Game.rated.is_(True),
                Game.white_delta.is_not(None),
            )
            .order_by(Game.ended_at)
            .limit(500)
        )
    ).all()
    points = []
    for ended, white_id, w_r, w_d, b_r, b_d in rows:
        rating, delta = (w_r, w_d) if white_id == user.id else (b_r, b_d)
        points.append({"t": ended.isoformat(), "rating": rating + (delta or 0)})
    return points


@router.get("/leaderboard")
async def leaderboard(tc: TimeClassParam, db: DB) -> list[dict[str, Any]]:
    """Top 50 established players. Cached for a minute: it's read far more than it changes."""
    cache_key = f"lb:{tc}"
    cached = await redis().get(cache_key)
    if cached:
        result: list[dict[str, Any]] = json.loads(cached)
        return result
    rows = (
        await db.execute(
            select(User.username, Rating)
            .join(Rating, Rating.user_id == User.id)
            .where(Rating.time_class == tc, Rating.games >= 5, Rating.rd <= 110)
            .order_by(Rating.rating.desc())
            .limit(50)
        )
    ).all()
    board = [
        {
            "rank": i + 1,
            "username": username,
            "rating": round(r.rating),
            "games": r.games,
            "wins": r.wins,
            "losses": r.losses,
            "draws": r.draws,
            "provisional": is_provisional(r.rd),
        }
        for i, (username, r) in enumerate(rows)
    ]
    await redis().set(cache_key, json.dumps(board), ex=60)
    return board


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chesscom_username: str | None = Field(default=None, max_length=25)


@router.patch("/me")
async def update_me(body: SettingsIn, claims: CurrentUser, db: DB) -> dict[str, Any]:
    user = await by_id(db, claims.user_id)
    if user is None:
        raise NotFound("Account not found.")
    user.chesscom_username = validate_chesscom(body.chesscom_username) if body.chesscom_username else None
    return {"chesscom_username": user.chesscom_username}


class DeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_username: str = Field(max_length=20)


@router.delete("/me")
async def delete_me(body: DeleteIn, claims: CurrentUser, db: DB) -> dict[str, bool]:
    """Deletes the account and everything attached to it (games, sessions, puzzles cascade)."""
    user = await by_id(db, claims.user_id)
    if user is None:
        raise NotFound("Account not found.")
    if body.confirm_username != user.username:
        raise AppError("Type your username exactly to confirm.", code="confirm_mismatch")
    await db.execute(delete(User).where(User.id == user.id))
    return {"ok": True}
