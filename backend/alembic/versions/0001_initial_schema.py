"""Initial schema: users, ratings, sessions, games, imported games, reviews, puzzles.

Revision ID: 0001
Revises:
Create Date: 2026-11-18 07:43:27.926419
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("username", sa.String(length=20), nullable=False),
        sa.Column("username_key", sa.String(length=20), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("google_sub", sa.String(length=255), nullable=True),
        sa.Column("chesscom_username", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("google_sub"),
        sa.UniqueConstraint("username_key"),
    )
    op.create_table(
        "games",
        sa.Column("id", sa.String(length=12), nullable=False),
        sa.Column("white_id", sa.UUID(), nullable=False),
        sa.Column("black_id", sa.UUID(), nullable=False),
        sa.Column("time_class", sa.String(length=10), nullable=False),
        sa.Column("initial_ms", sa.Integer(), nullable=False),
        sa.Column("increment_ms", sa.Integer(), nullable=False),
        sa.Column("rated", sa.Boolean(), nullable=False),
        sa.Column("result", sa.String(length=7), nullable=False),
        sa.Column("termination", sa.String(length=20), nullable=False),
        sa.Column("moves", sa.Text(), nullable=False),
        sa.Column("clocks_ms", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("opening_eco", sa.String(length=3), nullable=True),
        sa.Column("opening_name", sa.String(length=160), nullable=True),
        sa.Column("white_rating", sa.Integer(), nullable=False),
        sa.Column("black_rating", sa.Integer(), nullable=False),
        sa.Column("white_delta", sa.Integer(), nullable=True),
        sa.Column("black_delta", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["black_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["white_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_games_black", "games", ["black_id", "ended_at"], unique=False)
    op.create_index("ix_games_white", "games", ["white_id", "ended_at"], unique=False)
    op.create_table(
        "imported_games",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(length=255), nullable=True),
        sa.Column("white_name", sa.String(length=40), nullable=False),
        sa.Column("black_name", sa.String(length=40), nullable=False),
        sa.Column("white_rating", sa.Integer(), nullable=True),
        sa.Column("black_rating", sa.Integer(), nullable=True),
        sa.Column("time_class", sa.String(length=16), nullable=True),
        sa.Column("time_control", sa.String(length=32), nullable=True),
        sa.Column("result", sa.String(length=7), nullable=False),
        sa.Column("initial_fen", sa.String(length=100), nullable=True),
        sa.Column("moves", sa.Text(), nullable=False),
        sa.Column("opening_eco", sa.String(length=3), nullable=True),
        sa.Column("opening_name", sa.String(length=160), nullable=True),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "source", "external_id", name="uq_import_once"),
    )
    op.create_index(op.f("ix_imported_games_owner_id"), "imported_games", ["owner_id"], unique=False)
    op.create_table(
        "puzzles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("game_kind", sa.String(length=10), nullable=False),
        sa.Column("game_ref", sa.String(length=64), nullable=False),
        sa.Column("ply", sa.Integer(), nullable=False),
        sa.Column("fen", sa.String(length=100), nullable=False),
        sa.Column("solution", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("played", sa.String(length=5), nullable=False),
        sa.Column("classification", sa.String(length=12), nullable=False),
        sa.Column("win_drop", sa.Float(), nullable=False),
        sa.Column("box", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("solved", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "game_kind", "game_ref", "ply", name="uq_puzzle_source"),
    )
    op.create_index("ix_puzzles_due", "puzzles", ["user_id", "due_at"], unique=False)
    op.create_table(
        "ratings",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("time_class", sa.String(length=10), nullable=False),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("rd", sa.Float(), nullable=False),
        sa.Column("volatility", sa.Float(), nullable=False),
        sa.Column("games", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("losses", sa.Integer(), nullable=False),
        sa.Column("draws", sa.Integer(), nullable=False),
        sa.Column("peak", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("time_class IN ('bullet','blitz','rapid')", name="ratings_time_class"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "time_class"),
    )
    op.create_index("ix_ratings_leaderboard", "ratings", ["time_class", "rating"], unique=False)
    op.create_table(
        "reviews",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("game_kind", sa.String(length=10), nullable=False),
        sa.Column("game_ref", sa.String(length=64), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("accuracy_white", sa.Float(), nullable=False),
        sa.Column("accuracy_black", sa.Float(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_kind", "game_ref", name="uq_review_game"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_sessions_family_id"), "sessions", ["family_id"], unique=False)
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_family_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("reviews")
    op.drop_index("ix_ratings_leaderboard", table_name="ratings")
    op.drop_table("ratings")
    op.drop_index("ix_puzzles_due", table_name="puzzles")
    op.drop_table("puzzles")
    op.drop_index(op.f("ix_imported_games_owner_id"), table_name="imported_games")
    op.drop_table("imported_games")
    op.drop_index("ix_games_white", table_name="games")
    op.drop_index("ix_games_black", table_name="games")
    op.drop_table("games")
    op.drop_table("users")
