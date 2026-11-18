"""Creating users and looking them up."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..chess_core.glicko2 import is_provisional
from ..chess_core.timecontrols import TIME_CLASSES
from ..db.models import Rating, User
from ..errors import AppError, Conflict

USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,19}$")
RESERVED = {
    "admin",
    "administrator",
    "root",
    "system",
    "shahmaat",
    "support",
    "moderator",
    "anonymous",
    "guest",
    "bot",
}


def validate_username(username: str) -> str:
    username = username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise AppError(
            "Username must be 3–20 characters: letters, numbers, _ or -, starting with a letter or number.",
            code="invalid_username",
        )
    if username.lower() in RESERVED:
        raise AppError("That username is reserved.", code="invalid_username")
    return username


def validate_password(password: str) -> str:
    if len(password) < 8:
        raise AppError("Password must be at least 8 characters.", code="weak_password")
    if len(password) > 128:
        raise AppError("Password must be at most 128 characters.", code="weak_password")
    return password


async def create_user(
    db: AsyncSession, username: str, *, password_hash: str | None = None, google_sub: str | None = None
) -> User:
    username = validate_username(username)
    user = User(
        username=username, username_key=username.lower(), password_hash=password_hash, google_sub=google_sub
    )
    db.add(user)
    try:
        await db.flush()  # the unique index on username_key decides races, not a prior SELECT
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("That username is taken.", code="username_taken") from exc
    for tc in TIME_CLASSES:
        db.add(Rating(user_id=user.id, time_class=tc))
    await db.flush()
    return user


async def by_username(db: AsyncSession, username: str) -> User | None:
    return (await db.execute(select(User).where(User.username_key == username.lower()))).scalar_one_or_none()


async def by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


@dataclass(frozen=True, slots=True)
class RatingView:
    rating: int
    rd: int
    provisional: bool
    games: int


async def ratings_for(db: AsyncSession, user_id: uuid.UUID) -> dict[str, dict[str, object]]:
    rows = (await db.execute(select(Rating).where(Rating.user_id == user_id))).scalars().all()
    out: dict[str, dict[str, object]] = {}
    for r in rows:
        out[r.time_class] = {
            "rating": round(r.rating),
            "rd": round(r.rd),
            "provisional": is_provisional(r.rd),
            "games": r.games,
            "wins": r.wins,
            "losses": r.losses,
            "draws": r.draws,
            "peak": round(r.peak),
        }
    return out
