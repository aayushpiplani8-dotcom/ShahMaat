"""Puzzles from your own mistakes, scheduled with spaced repetition.

After a game is reviewed, every position where the player made a mistake or a
blunder (and wasn't already lost) becomes a puzzle: "find the move you missed".
Solving it pushes the puzzle into a later Leitner box (seen again in 3 days,
then a week, ...); failing sends it back to box 0. Repetition at growing gaps is
how memory research says patterns stick.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import chess

BOX_INTERVALS = (
    timedelta(days=1),
    timedelta(days=3),
    timedelta(days=7),
    timedelta(days=21),
    timedelta(days=60),
)
RETRY_AFTER_FAIL = timedelta(hours=1)
MIN_WIN_BEFORE = 30.0  # positions already lost aren't instructive


@dataclass(frozen=True, slots=True)
class PuzzleSeed:
    ply: int
    fen: str
    solution: list[str]
    played: str
    classification: str
    win_drop: float


def extract(
    review: dict[str, Any], moves: list[str], player_is_white: bool, initial_fen: str | None = None
) -> list[PuzzleSeed]:
    board = chess.Board(initial_fen or chess.STARTING_FEN)
    seeds: list[PuzzleSeed] = []
    for i, item in enumerate(review["moves"]):
        mover_white = board.turn == chess.WHITE
        if mover_white == player_is_white and item["class"] in ("mistake", "blunder") and item["pv"]:
            win_before = _mover_win(item["cp_before"], mover_white)
            if win_before >= MIN_WIN_BEFORE:
                seeds.append(
                    PuzzleSeed(
                        ply=i,
                        fen=board.fen(),
                        solution=item["pv"][:3],
                        played=item["uci"],
                        classification=item["class"],
                        win_drop=float(item["win_drop"]),
                    )
                )
        board.push(chess.Move.from_uci(moves[i]))
    return seeds


def _mover_win(cp_white: int, mover_white: bool) -> float:
    from .review import win_percent

    w = win_percent(cp_white)
    return w if mover_white else 100 - w


def is_correct(fen: str, solution: list[str], attempt: str) -> bool:
    """The engine's move, or any move that checkmates on the spot, solves the puzzle."""
    if not solution:
        return False
    if attempt == solution[0]:
        return True
    board = chess.Board(fen)
    try:
        move = chess.Move.from_uci(attempt)
    except ValueError:
        return False
    if move not in board.legal_moves:
        return False
    board.push(move)
    return board.is_checkmate()


def schedule(box: int, solved: bool, now: datetime) -> tuple[int, datetime]:
    """Next (box, due_at) after an attempt."""
    if not solved:
        return 0, now + RETRY_AFTER_FAIL
    current = max(0, min(box, len(BOX_INTERVALS) - 1))
    return min(box + 1, len(BOX_INTERVALS) - 1), now + BOX_INTERVALS[current]
