"""Saving a finished game to Postgres and updating ratings — in ONE transaction.

Either both happen or neither does: you can never get a saved game without the
rating change, or a rating change without the game.

Idempotent: the game's id is the primary key and the insert is
`ON CONFLICT DO NOTHING`. If archiving runs twice (a retry after a crash, two
servers racing), the second run finds the row and changes nothing, so ratings
are never counted twice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..chess_core import glicko2
from ..db import session_scope
from ..db.models import Game, Rating
from .state import LiveGame

SCORES = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}


def _dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


async def archive_game(game: LiveGame) -> dict[str, int] | None:
    """Persists the game; returns rating changes {"white": +8, "black": -8} for rated games."""
    if game.result not in SCORES:
        return None  # aborted games aren't kept

    async with session_scope() as db:
        stmt = (
            pg_insert(Game)
            .values(
                id=game.id,
                white_id=uuid.UUID(game.white.id),
                black_id=uuid.UUID(game.black.id),
                time_class=game.time_class,
                initial_ms=game.initial_ms,
                increment_ms=game.increment_ms,
                rated=game.rated,
                result=game.result,
                termination=game.termination or "unknown",
                moves=" ".join(game.moves),
                clocks_ms=game.clocks_ms,
                opening_eco=(game.opening or {}).get("eco"),
                opening_name=(game.opening or {}).get("name"),
                white_rating=game.white.rating,
                black_rating=game.black.rating,
                created_at=_dt(game.created_ms),
                ended_at=_dt(game.ended_ms or game.created_ms),
            )
            .on_conflict_do_nothing(index_elements=[Game.id])
            .returning(Game.id)
        )
        inserted = (await db.execute(stmt)).scalar_one_or_none()
        if inserted is None:
            existing = await db.get(Game, game.id)
            if existing and existing.white_delta is not None and existing.black_delta is not None:
                return {"white": existing.white_delta, "black": existing.black_delta}
            return None

        if not game.rated:
            return None

        # Lock both rating rows. Always in the same order (sorted ids), so two games
        # finishing at once can't deadlock each other.
        ids = sorted([uuid.UUID(game.white.id), uuid.UUID(game.black.id)])
        rows = (
            (
                await db.execute(
                    select(Rating)
                    .where(Rating.user_id.in_(ids), Rating.time_class == game.time_class)
                    .order_by(Rating.user_id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        by_user = {r.user_id: r for r in rows}
        w_row = by_user[uuid.UUID(game.white.id)]
        b_row = by_user[uuid.UUID(game.black.id)]

        score = SCORES[game.result]
        new_w, new_b = glicko2.rate_game(
            glicko2.Glicko(w_row.rating, w_row.rd, w_row.volatility),
            glicko2.Glicko(b_row.rating, b_row.rd, b_row.volatility),
            score,
        )
        deltas = {
            "white": round(new_w.rating) - round(w_row.rating),
            "black": round(new_b.rating) - round(b_row.rating),
        }
        now = datetime.now(UTC)
        for row, new, s in ((w_row, new_w, score), (b_row, new_b, 1.0 - score)):
            row.rating, row.rd, row.volatility = new.rating, new.rd, new.volatility
            row.games += 1
            row.wins += s == 1.0
            row.losses += s == 0.0
            row.draws += s == 0.5
            row.peak = max(row.peak, new.rating)
            row.updated_at = now

        saved = await db.get(Game, game.id)
        assert saved is not None
        saved.white_delta, saved.black_delta = deltas["white"], deltas["black"]
        return deltas
