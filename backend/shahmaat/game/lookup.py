"""Finding a game wherever it lives: Redis (being played), Postgres (finished), or an import."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..chess_core.rules import san_list
from ..chess_core.timecontrols import key_for
from ..db.models import Game, ImportedGame, User
from ..errors import AppError, Forbidden, NotFound
from . import store

GameKind = Literal["live", "imported"]


@dataclass(slots=True)
class ReviewTarget:
    kind: GameKind
    ref: str
    moves: list[str]
    initial_fen: str | None
    white_user_id: str | None  # ShahMaat users (live games)
    black_user_id: str | None
    white_name: str
    black_name: str
    owner_id: str | None  # imported games: who imported it


def archived_view(game: Game, white: User, black: User) -> dict[str, Any]:
    moves = game.moves.split() if game.moves else []
    return {
        "id": game.id,
        "white": {"id": str(white.id), "username": white.username, "rating": game.white_rating},
        "black": {"id": str(black.id), "username": black.username, "rating": game.black_rating},
        "tc": {
            "key": key_for(game.initial_ms, game.increment_ms),
            "initial_ms": game.initial_ms,
            "increment_ms": game.increment_ms,
            "time_class": game.time_class,
        },
        "rated": game.rated,
        "moves": moves,
        "san": san_list(moves),
        "clocks_ms": game.clocks_ms,
        "status": "ended",
        "result": game.result,
        "termination": game.termination,
        "opening": {"eco": game.opening_eco, "name": game.opening_name} if game.opening_eco else None,
        "rating_deltas": (
            {"white": game.white_delta, "black": game.black_delta} if game.white_delta is not None else None
        ),
        "created_at": game.created_at.isoformat(),
        "ended_at": game.ended_at.isoformat(),
    }


async def load_archived(db: AsyncSession, game_id: str) -> dict[str, Any] | None:
    w, b = aliased(User), aliased(User)
    row = (
        await db.execute(
            select(Game, w, b)
            .join(w, w.id == Game.white_id)
            .join(b, b.id == Game.black_id)
            .where(Game.id == game_id)
        )
    ).first()
    if row is None:
        return None
    return archived_view(*row)


def imported_view(g: ImportedGame) -> dict[str, Any]:
    moves = g.moves.split() if g.moves else []
    return {
        "id": str(g.id),
        "source": g.source,
        "url": g.url,
        "white": {"username": g.white_name, "rating": g.white_rating},
        "black": {"username": g.black_name, "rating": g.black_rating},
        "time_class": g.time_class,
        "time_control": g.time_control,
        "result": g.result,
        "initial_fen": g.initial_fen,
        "moves": moves,
        "san": san_list(moves, g.initial_fen),
        "opening": {"eco": g.opening_eco, "name": g.opening_name} if g.opening_eco else None,
        "played_at": g.played_at.isoformat() if g.played_at else None,
    }


async def review_target(db: AsyncSession, kind: str, ref: str, viewer_id: str | None) -> ReviewTarget:
    if kind == "live":
        if len(ref) > 12:
            raise NotFound("Game not found.")
        live = await store.load(ref)
        if live and live[0].status == "active":
            # Fair play: no engine help while the game is still being played.
            raise Forbidden("Analysis is available once the game is over.", code="game_in_progress")
        game = await db.get(Game, ref)
        if game is None:
            raise NotFound("Game not found.")
        names = {
            u.id: u.username
            for u in (
                await db.execute(select(User).where(User.id.in_([game.white_id, game.black_id])))
            ).scalars()
        }
        return ReviewTarget(
            kind="live",
            ref=ref,
            moves=game.moves.split() if game.moves else [],
            initial_fen=None,
            white_user_id=str(game.white_id),
            black_user_id=str(game.black_id),
            white_name=names.get(game.white_id, "?"),
            black_name=names.get(game.black_id, "?"),
            owner_id=None,
        )
    if kind == "imported":
        try:
            imported_id = uuid.UUID(ref)
        except ValueError as exc:
            raise NotFound("Game not found.") from exc
        imported = await db.get(ImportedGame, imported_id)
        if imported is None or viewer_id is None or str(imported.owner_id) != viewer_id:
            raise NotFound("Game not found.")
        return ReviewTarget(
            kind="imported",
            ref=ref,
            moves=imported.moves.split(),
            initial_fen=imported.initial_fen,
            white_user_id=None,
            black_user_id=None,
            white_name=imported.white_name,
            black_name=imported.black_name,
            owner_id=str(imported.owner_id),
        )
    raise AppError("Unknown game kind.")
