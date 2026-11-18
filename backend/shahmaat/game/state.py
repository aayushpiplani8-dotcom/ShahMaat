"""The shape of a live game, as stored in Redis and as sent to browsers."""

from __future__ import annotations

import secrets
import string
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import chess

from ..chess_core.clock import (
    ClockState,
    clock_running,
    first_move_deadline_ms,
    flag_deadline_ms,
    remaining_ms,
)

Color = Literal["white", "black"]
Status = Literal["active", "ended"]

# How long a player may be disconnected before the opponent can claim the win.
CLAIM_AFTER_MS = 30_000

_ID_ALPHABET = string.ascii_letters + string.digits


def new_game_id() -> str:
    """10 random characters (62^10 ≈ 8e17): unguessable, so private games stay private."""
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(10))


def other(color: Color) -> Color:
    return "black" if color == "white" else "white"


@dataclass(slots=True)
class Player:
    id: str
    username: str
    rating: int
    provisional: bool


@dataclass(slots=True)
class LiveGame:
    id: str
    white: Player
    black: Player
    tc_key: str
    initial_ms: int
    increment_ms: int
    time_class: str
    rated: bool
    source: str  # queue | challenge | rematch
    clock: ClockState
    created_ms: int
    moves: list[str] = field(default_factory=list)
    san: list[str] = field(default_factory=list)
    clocks_ms: list[int] = field(default_factory=list)
    fen: str = chess.STARTING_FEN
    status: Status = "active"
    result: str | None = None
    termination: str | None = None
    ended_ms: int | None = None
    draw_offer: Color | None = None
    rematch_offer: Color | None = None
    rematch_game: str | None = None
    disconnected: dict[str, int | None] = field(default_factory=lambda: {"white": None, "black": None})
    opening: dict[str, str] | None = None
    rating_deltas: dict[str, int] | None = None
    archived: bool = False

    # ---------------------------------------------------------------- helpers
    @property
    def ply(self) -> int:
        return len(self.moves)

    @property
    def white_to_move(self) -> bool:
        return self.ply % 2 == 0

    @property
    def turn(self) -> Color:
        return "white" if self.white_to_move else "black"

    def color_of(self, user_id: str) -> Color | None:
        if self.white.id == user_id:
            return "white"
        if self.black.id == user_id:
            return "black"
        return None

    def player(self, color: Color) -> Player:
        return self.white if color == "white" else self.black

    def next_deadline_ms(self) -> int | None:
        """When the referee must look at this game again (abort or flag), if ever."""
        if self.status != "active":
            return None
        return first_move_deadline_ms(self.clock, self.ply) or flag_deadline_ms(
            self.clock, self.white_to_move, self.ply
        )

    # ---------------------------------------------------------- serialisation
    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["clock"] = self.clock.to_dict()
        return d

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> LiveGame:
        d = dict(d)
        d["white"] = Player(**d["white"])
        d["black"] = Player(**d["black"])
        d["clock"] = ClockState.from_dict(d["clock"])
        return cls(**d)

    def snapshot(self, now_ms: int, version: int) -> dict[str, Any]:
        """What browsers see. Clocks are computed for `now_ms` so every client agrees."""
        white_ms, black_ms = remaining_ms(self.clock, self.white_to_move, self.ply, now_ms)
        if self.status == "ended":
            white_ms, black_ms = self.clock.white_ms, self.clock.black_ms
        return {
            "id": self.id,
            "version": version,
            "white": asdict(self.white),
            "black": asdict(self.black),
            "tc": {
                "key": self.tc_key,
                "initial_ms": self.initial_ms,
                "increment_ms": self.increment_ms,
                "time_class": self.time_class,
            },
            "rated": self.rated,
            "moves": self.moves,
            "san": self.san,
            "clocks_ms": self.clocks_ms,
            "fen": self.fen,
            "turn": self.turn,
            "ply": self.ply,
            "clock": {
                "white_ms": max(0, white_ms),
                "black_ms": max(0, black_ms),
                "running": clock_running(self.ply) and self.status == "active",
            },
            "first_move_deadline_ms": first_move_deadline_ms(self.clock, self.ply)
            if self.status == "active"
            else None,
            "status": self.status,
            "result": self.result,
            "termination": self.termination,
            "draw_offer": self.draw_offer,
            "rematch_offer": self.rematch_offer,
            "rematch_game": self.rematch_game,
            "disconnected": self.disconnected,
            "claim_after_ms": CLAIM_AFTER_MS,
            "opening": self.opening,
            "rating_deltas": self.rating_deltas,
            "server_now_ms": now_ms,
        }
