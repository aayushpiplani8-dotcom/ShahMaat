"""chess.com import: browse a player's public games, import one, review it here."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, cast, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.deps import CurrentUser
from ..chess_core.openings import identify
from ..chess_core.rules import parse_pgn
from ..db import get_session
from ..db.models import ImportedGame, Review
from ..errors import NotFound
from ..game.lookup import imported_view
from ..security import ratelimit
from ..services import chesscom

router = APIRouter(prefix="/api", tags=["import"])
DB = Annotated[AsyncSession, Depends(get_session)]


@router.get("/chesscom/{username}/archives")
async def cc_archives(username: str, user: CurrentUser) -> dict[str, Any]:
    await ratelimit.hit(f"cc:{user.user_id}", limit=60, window_s=600)
    return {"months": await chesscom.archives(username)}


@router.get("/chesscom/{username}/games")
async def cc_games(
    username: str, user: CurrentUser, month: Annotated[str, Query(max_length=7)]
) -> dict[str, Any]:
    await ratelimit.hit(f"cc:{user.user_id}", limit=60, window_s=600)
    games = await chesscom.month_games(username, month)
    return {"games": [chesscom.summarize(g) for g in games]}


class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=25)
    month: str = Field(max_length=7)
    uuid: str = Field(max_length=64)


@router.post("/imports")
async def import_game(body: ImportIn, user: CurrentUser, db: DB) -> dict[str, str]:
    """Imports by reference (player + month + game uuid). The server fetches the PGN from
    chess.com itself, so a client can't slip in a doctored game under someone's name."""
    await ratelimit.hit(f"import:{user.user_id}", limit=60, window_s=3600)
    games = await chesscom.month_games(body.username, body.month)
    found = next((g for g in games if g.get("uuid") == body.uuid), None)
    if found is None:
        raise NotFound("That game isn't in this player's archive.")
    pgn_game, moves = parse_pgn(found["pgn"])
    initial_fen = found.get("initial_setup") or None
    if initial_fen and initial_fen.startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq"):
        initial_fen = None
    opening = identify(moves, initial_fen)
    white, black = found.get("white", {}), found.get("black", {})
    stmt = (
        pg_insert(ImportedGame)
        .values(
            id=uuid.uuid4(),
            owner_id=user.user_id,
            source="chesscom",
            external_id=body.uuid,
            url=found.get("url"),
            white_name=str(white.get("username", "?"))[:40],
            black_name=str(black.get("username", "?"))[:40],
            white_rating=white.get("rating"),
            black_rating=black.get("rating"),
            time_class=found.get("time_class"),
            time_control=str(found.get("time_control", ""))[:32],
            result=pgn_game.headers.get("Result", "*")[:7],
            initial_fen=initial_fen,
            moves=" ".join(moves),
            opening_eco=opening.eco if opening else None,
            opening_name=opening.name if opening else None,
            played_at=datetime.fromtimestamp(found["end_time"], tz=UTC) if found.get("end_time") else None,
        )
        .on_conflict_do_update(constraint="uq_import_once", set_={"url": found.get("url")})
        .returning(ImportedGame.id)
    )
    imported_id = (await db.execute(stmt)).scalar_one()
    return {"id": str(imported_id)}


@router.get("/imports")
async def my_imports(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(ImportedGame, Review.accuracy_white, Review.accuracy_black)
            .outerjoin(
                Review,
                (Review.game_kind == "imported") & (Review.game_ref == cast(ImportedGame.id, String)),
            )
            .where(ImportedGame.owner_id == user.user_id)
            .order_by(ImportedGame.played_at.desc().nulls_last())
            .limit(100)
        )
    ).all()
    out = []
    for g, acc_w, acc_b in rows:
        out.append(
            {
                "id": str(g.id),
                "white": {"username": g.white_name, "rating": g.white_rating},
                "black": {"username": g.black_name, "rating": g.black_rating},
                "result": g.result,
                "time_class": g.time_class,
                "opening": g.opening_name,
                "played_at": g.played_at.isoformat() if g.played_at else None,
                "accuracy": {"white": acc_w, "black": acc_b} if acc_w is not None else None,
            }
        )
    return out


@router.get("/imports/{imported_id}")
async def get_import(imported_id: str, user: CurrentUser, db: DB) -> dict[str, Any]:
    try:
        key = uuid.UUID(imported_id)
    except ValueError as exc:
        raise NotFound("Game not found.") from exc
    g = await db.get(ImportedGame, key)
    if g is None or g.owner_id != user.user_id:
        raise NotFound("Game not found.")
    return imported_view(g)
