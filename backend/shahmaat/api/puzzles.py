"""'Learn from your mistakes': puzzles built from your own reviewed games."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.deps import CurrentUser
from ..chess_core import puzzles as logic
from ..db import get_session
from ..db.models import Puzzle
from ..errors import NotFound
from ..security import ratelimit

router = APIRouter(prefix="/api/puzzles", tags=["puzzles"])
DB = Annotated[AsyncSession, Depends(get_session)]


def _public(p: Puzzle) -> dict[str, Any]:
    # The solution is NOT sent: the server checks answers, so it can't be read from the network tab.
    return {
        "id": str(p.id),
        "fen": p.fen,
        "played": p.played,
        "classification": p.classification,
        "game_kind": p.game_kind,
        "game_ref": p.game_ref,
        "ply": p.ply,
        "box": p.box,
        "attempts": p.attempts,
        "solved": p.solved,
    }


@router.get("/stats")
async def stats(user: CurrentUser, db: DB) -> dict[str, Any]:
    now = datetime.now(UTC)
    total, due, mastered = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Puzzle.due_at <= now),
                func.count().filter(Puzzle.box >= 3),
            ).where(Puzzle.user_id == user.user_id)
        )
    ).one()
    next_due = (
        await db.execute(
            select(func.min(Puzzle.due_at)).where(Puzzle.user_id == user.user_id, Puzzle.due_at > now)
        )
    ).scalar_one_or_none()
    return {
        "total": total,
        "due": due,
        "mastered": mastered,
        "next_due_at": next_due.isoformat() if next_due else None,
    }


@router.get("/next")
async def next_puzzle(user: CurrentUser, db: DB) -> dict[str, Any]:
    p = (
        await db.execute(
            select(Puzzle)
            .where(Puzzle.user_id == user.user_id, Puzzle.due_at <= datetime.now(UTC))
            .order_by(Puzzle.due_at, Puzzle.win_drop.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {"puzzle": _public(p) if p else None}


class AttemptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    move: str = Field(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")


@router.post("/{puzzle_id}/attempt")
async def attempt(puzzle_id: str, body: AttemptIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    await ratelimit.hit(f"puzzle:{user.user_id}", limit=120, window_s=600)
    try:
        key = uuid.UUID(puzzle_id)
    except ValueError as exc:
        raise NotFound("Puzzle not found.") from exc
    p = (await db.execute(select(Puzzle).where(Puzzle.id == key).with_for_update())).scalar_one_or_none()
    if p is None or p.user_id != user.user_id:
        raise NotFound("Puzzle not found.")
    correct = logic.is_correct(p.fen, p.solution, body.move)
    p.attempts += 1
    p.solved += int(correct)
    p.box, p.due_at = logic.schedule(p.box, correct, datetime.now(UTC))
    return {"correct": correct, "solution": p.solution, "box": p.box, "due_at": p.due_at.isoformat()}
