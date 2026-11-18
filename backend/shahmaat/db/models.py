"""Database tables (SQLAlchemy 2.0 typed models).

Live games are NOT here: while a game is being played its state lives in Redis
(fast, shared between servers). A game is written to Postgres once, when it ends,
inside the same transaction that updates both players' ratings.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(20))
    # Lower-cased copy with a unique index: "Magnus" and "magnus" can't both exist.
    username_key: Mapped[str] = mapped_column(String(20), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    # Google's stable account id ("sub"). We never store the Google email address.
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    chesscom_username: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Rating(Base):
    """One Glicko-2 rating per user per time class (bullet / blitz / rapid)."""

    __tablename__ = "ratings"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    time_class: Mapped[str] = mapped_column(String(10), primary_key=True)
    rating: Mapped[float] = mapped_column(Float, default=1500.0)
    rd: Mapped[float] = mapped_column(Float, default=350.0)
    volatility: Mapped[float] = mapped_column(Float, default=0.06)
    games: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    draws: Mapped[int] = mapped_column(Integer, default=0)
    peak: Mapped[float] = mapped_column(Float, default=1500.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint("time_class IN ('bullet','blitz','rapid')", name="ratings_time_class"),
        Index("ix_ratings_leaderboard", "time_class", "rating"),
    )


class Session(Base):
    """A refresh token. Tokens rotate on every use; all tokens from one login share a family_id."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    # HMAC-SHA256 of the token. A database leak doesn't hand out usable tokens.
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(256))


class Game(Base):
    """A finished game played on ShahMaat."""

    __tablename__ = "games"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    white_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    black_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    time_class: Mapped[str] = mapped_column(String(10))
    initial_ms: Mapped[int] = mapped_column(Integer)
    increment_ms: Mapped[int] = mapped_column(Integer)
    rated: Mapped[bool] = mapped_column(Boolean, default=True)
    result: Mapped[str] = mapped_column(String(7))  # "1-0", "0-1", "1/2-1/2", "*" (aborted)
    termination: Mapped[str] = mapped_column(String(20))
    moves: Mapped[str] = mapped_column(Text, default="")  # space-separated UCI moves
    clocks_ms: Mapped[list[int]] = mapped_column(JSONB, default=list)  # mover's time left after each move
    opening_eco: Mapped[str | None] = mapped_column(String(3))
    opening_name: Mapped[str | None] = mapped_column(String(160))
    white_rating: Mapped[int] = mapped_column(Integer)
    black_rating: Mapped[int] = mapped_column(Integer)
    white_delta: Mapped[int | None] = mapped_column(Integer)
    black_delta: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_games_white", "white_id", "ended_at"),
        Index("ix_games_black", "black_id", "ended_at"),
    )


class ImportedGame(Base):
    """A chess.com game a user imported for review."""

    __tablename__ = "imported_games"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16), default="chesscom")
    external_id: Mapped[str] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(String(255))
    white_name: Mapped[str] = mapped_column(String(40))
    black_name: Mapped[str] = mapped_column(String(40))
    white_rating: Mapped[int | None] = mapped_column(Integer)
    black_rating: Mapped[int | None] = mapped_column(Integer)
    time_class: Mapped[str | None] = mapped_column(String(16))
    time_control: Mapped[str | None] = mapped_column(String(32))
    result: Mapped[str] = mapped_column(String(7))
    initial_fen: Mapped[str | None] = mapped_column(String(100))
    moves: Mapped[str] = mapped_column(Text)
    opening_eco: Mapped[str | None] = mapped_column(String(3))
    opening_name: Mapped[str | None] = mapped_column(String(160))
    played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("owner_id", "source", "external_id", name="uq_import_once"),)


class Review(Base):
    """Engine review of a game: every move classified, plus accuracy per side."""

    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_kind: Mapped[str] = mapped_column(String(10))  # "live" | "imported"
    game_ref: Mapped[str] = mapped_column(String(64))
    depth: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    accuracy_white: Mapped[float] = mapped_column(Float)
    accuracy_black: Mapped[float] = mapped_column(Float)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("game_kind", "game_ref", name="uq_review_game"),)


class Puzzle(Base):
    """A position where the user went wrong, turned into a puzzle with spaced repetition."""

    __tablename__ = "puzzles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    game_kind: Mapped[str] = mapped_column(String(10))
    game_ref: Mapped[str] = mapped_column(String(64))
    ply: Mapped[int] = mapped_column(Integer)
    fen: Mapped[str] = mapped_column(String(100))
    solution: Mapped[list[str]] = mapped_column(JSONB)  # UCI moves; user plays the even-indexed ones
    played: Mapped[str] = mapped_column(String(5))  # the move actually played in the game
    classification: Mapped[str] = mapped_column(String(12))
    win_drop: Mapped[float] = mapped_column(Float)
    box: Mapped[int] = mapped_column(Integer, default=0)  # Leitner box 0..4
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    solved: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "game_kind", "game_ref", "ply", name="uq_puzzle_source"),
        Index("ix_puzzles_due", "user_id", "due_at"),
    )
