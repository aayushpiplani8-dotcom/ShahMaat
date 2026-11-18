"""Game reviews: the browser's Stockfish sends evaluations, the server scores and stores them.

Also turns the requesting player's mistakes into puzzles.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.deps import CurrentUser, OptionalUser, client_ip
from ..auth.users import by_id
from ..chess_core import puzzles as puzzle_logic
from ..chess_core.review import EngineLine, review_game
from ..chess_core.rules import STANDARD_FEN
from ..db import get_session
from ..db.models import Puzzle, Review
from ..errors import AppError, NotFound
from ..game.lookup import ReviewTarget, review_target
from ..security import ratelimit

router = APIRouter(prefix="/api/reviews", tags=["reviews"])
DB = Annotated[AsyncSession, Depends(get_session)]
MAX_PLIES = 600


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cp: Annotated[int | None, Field(ge=-100_000, le=100_000)] = None
    mate: Annotated[int | None, Field(ge=-500, le=500)] = None
    best: Annotated[str | None, Field(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")] = None
    pv: Annotated[
        list[Annotated[str, Field(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")]], Field(max_length=12)
    ] = []

    def to_line(self) -> EngineLine:
        return EngineLine(cp=self.cp, mate=self.mate, best=self.best, pv=list(self.pv))


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    depth: Annotated[int, Field(ge=6, le=40)]
    lines: Annotated[list[LineIn], Field(max_length=MAX_PLIES + 1)]


class ScoreIn(ReviewIn):
    moves: Annotated[
        list[Annotated[str, Field(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")]], Field(max_length=MAX_PLIES)
    ]
    initial_fen: Annotated[str | None, Field(max_length=100)] = None


def _stored_view(review: Review) -> dict[str, Any]:
    return {**review.data, "depth": review.depth, "created_at": review.created_at.isoformat()}


@router.post("/score")
async def score_only(body: ScoreIn, request: Request, user: OptionalUser) -> dict[str, Any]:
    """Scores any move list (analysis board, pasted PGN) without storing anything."""
    key = f"score:{user.user_id}" if user else f"score:ip:{client_ip(request)}"
    await ratelimit.hit(key, limit=60, window_s=3600)
    fen = body.initial_fen if body.initial_fen and body.initial_fen != STANDARD_FEN else None
    try:
        return review_game(body.moves, [ln.to_line() for ln in body.lines], initial_fen=fen)
    except ValueError as exc:  # bad FEN
        raise AppError("Invalid starting position.") from exc


@router.get("/{kind}/{ref}")
async def get_review(kind: str, ref: str, db: DB, user: OptionalUser) -> dict[str, Any]:
    target = await review_target(db, kind, ref, str(user.user_id) if user else None)
    review = (
        await db.execute(select(Review).where(Review.game_kind == target.kind, Review.game_ref == target.ref))
    ).scalar_one_or_none()
    if review is None:
        raise NotFound("This game hasn't been reviewed yet.", code="no_review")
    return _stored_view(review)


@router.post("/{kind}/{ref}")
async def create_review(kind: str, ref: str, body: ReviewIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    await ratelimit.hit(f"review:{user.user_id}", limit=40, window_s=3600)
    target = await review_target(db, kind, ref, str(user.user_id))
    data = review_game(target.moves, [ln.to_line() for ln in body.lines], initial_fen=target.initial_fen)

    existing = (
        await db.execute(
            select(Review)
            .where(Review.game_kind == target.kind, Review.game_ref == target.ref)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is None:
        review = Review(
            game_kind=target.kind,
            game_ref=target.ref,
            depth=body.depth,
            created_by=user.user_id,
            accuracy_white=data["accuracy"]["white"],
            accuracy_black=data["accuracy"]["black"],
            data=data,
        )
        db.add(review)
    elif body.depth >= existing.depth:  # a deeper (or equal) review replaces a shallower one
        existing.depth, existing.data = body.depth, data
        existing.accuracy_white, existing.accuracy_black = (
            data["accuracy"]["white"],
            data["accuracy"]["black"],
        )
        existing.created_at = datetime.now(UTC)
        review = existing
    else:
        review = existing
    await db.flush()

    created = await _make_puzzles(db, target, review.data, str(user.user_id))
    return {**_stored_view(review), "puzzles_created": created}


@router.post("/{kind}/{ref}/puzzles")
async def puzzles_from_stored_review(kind: str, ref: str, db: DB, user: CurrentUser) -> dict[str, int]:
    """Your opponent already reviewed the game: build YOUR puzzles from that stored review
    without re-running the engine."""
    target = await review_target(db, kind, ref, str(user.user_id))
    review = (
        await db.execute(select(Review).where(Review.game_kind == target.kind, Review.game_ref == target.ref))
    ).scalar_one_or_none()
    if review is None:
        raise NotFound("This game hasn't been reviewed yet.", code="no_review")
    return {"puzzles_created": await _make_puzzles(db, target, review.data, str(user.user_id))}


async def _make_puzzles(db: AsyncSession, target: ReviewTarget, data: dict[str, Any], user_id: str) -> int:
    """Which side was the requester? Live games: by account. Imports: by linked chess.com name."""
    if target.kind == "live":
        if user_id == target.white_user_id:
            is_white = True
        elif user_id == target.black_user_id:
            is_white = False
        else:
            return 0
    else:
        account = await by_id(db, uuid.UUID(user_id))
        name = (account.chesscom_username or "").lower() if account else ""
        if name and name == target.white_name.lower():
            is_white = True
        elif name and name == target.black_name.lower():
            is_white = False
        else:
            return 0

    seeds = puzzle_logic.extract(data, target.moves, is_white, target.initial_fen)
    if not seeds:
        return 0
    stmt = (
        pg_insert(Puzzle)
        .values(
            [
                {
                    "id": uuid.uuid4(),
                    "user_id": uuid.UUID(user_id),
                    "game_kind": target.kind,
                    "game_ref": target.ref,
                    "ply": s.ply,
                    "fen": s.fen,
                    "solution": s.solution,
                    "played": s.played,
                    "classification": s.classification,
                    "win_drop": s.win_drop,
                    "due_at": datetime.now(UTC),
                }
                for s in seeds
            ]
        )
        .on_conflict_do_nothing(constraint="uq_puzzle_source")
        .returning(Puzzle.id)
    )
    return len((await db.execute(stmt)).all())
