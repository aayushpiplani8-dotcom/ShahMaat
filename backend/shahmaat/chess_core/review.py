"""Game review maths: turn engine evaluations into move labels and accuracy.

Where the work happens
----------------------
Stockfish runs in the player's browser (WebAssembly), so analysis is free and
unlimited for the server. The browser sends the raw numbers here; this module
re-checks them against the actual game (python-chess replays every move, and
every engine move must be legal in its position) and does the scoring. Keeping
the scoring on the server means one implementation, one set of tests, and a
review that can be stored and shared.

The maths
---------
* Win% turns centipawns into a chance of winning with the logistic curve Lichess
  fitted to millions of games. Judging by win% means dropping 3 pawns while a
  queen up barely matters, but dropping 1 pawn in a level position does.
* Move accuracy decays exponentially with the win% lost (Lichess's curve).
* Game accuracy mixes a volatility-weighted mean (slips in sharp positions count
  more) with a harmonic mean (one awful move drags it down), like Lichess.
* Phase accuracy (opening / middlegame / endgame) is ShahMaat's own addition, so
  players see WHERE in the game they lose points.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import pstdev
from typing import Any, Literal

import chess

from ..errors import AppError
from .openings import book_plies, identify

WIN_SLOPE = 0.00368208
DECAY = 0.04354415386753951
MATE_CP = 10_000
MATE_THRESHOLD = 9_000
MAX_PV = 6

MoveClass = Literal["book", "forced", "best", "excellent", "good", "inaccuracy", "mistake", "blunder"]
CLASSES: tuple[MoveClass, ...] = (
    "book",
    "forced",
    "best",
    "excellent",
    "good",
    "inaccuracy",
    "mistake",
    "blunder",
)
Phase = Literal["opening", "middlegame", "endgame"]


@dataclass(frozen=True, slots=True)
class EngineLine:
    """The engine's view of one position, as sent by the browser (White's point of view)."""

    cp: int | None
    mate: int | None
    best: str | None
    pv: list[str]

    def as_cp(self) -> int:
        if self.mate is not None:
            if self.mate == 0:
                return 0
            sign = 1 if self.mate > 0 else -1
            return sign * (MATE_CP - 10 * min(abs(self.mate), 99))
        return max(-MATE_CP, min(MATE_CP, self.cp or 0))


def win_percent(cp: float, slope: float = WIN_SLOPE) -> float:
    """White's chance of winning, 0–100."""
    c = max(-1000.0, min(1000.0, cp))
    return 50 + 50 * (2 / (1 + math.exp(-slope * c)) - 1)


def move_accuracy(win_before: float, win_after: float, decay: float = DECAY) -> float:
    if win_after >= win_before:
        return 100.0
    drop = win_before - win_after
    raw = 103.1668100711649 * math.exp(-decay * drop) - 3.166924740191411
    return max(0.0, min(100.0, raw + 1))  # +1: allowance for engine noise, as in Lichess


def classify(win_drop: float, played_best: bool) -> MoveClass:
    if played_best:
        return "best"
    if win_drop < 2:
        return "excellent"
    if win_drop < 5:
        return "good"
    if win_drop < 10:
        return "inaccuracy"
    if win_drop < 20:
        return "mistake"
    return "blunder"


def game_accuracy(evals_cp: list[int], scale: float = 1.0) -> tuple[float, float]:
    """(white, black) accuracy for a whole game; evals_cp has one entry per position."""
    wins = [win_percent(cp) for cp in evals_cp]
    n_moves = len(wins) - 1
    if n_moves <= 0:
        return 100.0, 100.0

    size = min(min(8, max(2, n_moves // 10)), len(wins))
    windows = [wins[:size]] * max(0, size - 2) + [wins[i : i + size] for i in range(len(wins) - size + 1)]
    weights = [min(12.0, max(0.5, pstdev(w))) for w in windows]

    sides: dict[bool, list[tuple[float, float]]] = {True: [], False: []}
    for i in range(n_moves):
        white = i % 2 == 0
        before = wins[i] if white else 100 - wins[i]
        after = wins[i + 1] if white else 100 - wins[i + 1]
        weight = weights[i] if i < len(weights) else 1.0
        sides[white].append((move_accuracy(before, after), weight))

    def score(items: list[tuple[float, float]]) -> float:
        if not items:
            return 100.0
        total_w = sum(w for _, w in items)
        weighted = sum(a * w for a, w in items) / total_w
        harmonic = len(items) / sum(1 / max(a, 0.5) for a, _ in items)
        raw = (weighted + harmonic) / 2
        return round(max(0.0, min(100.0, 100 - scale * (100 - raw))), 1)

    return score(sides[True]), score(sides[False])


def _material(board: chess.Board) -> int:
    values = {chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
    return sum(len(board.pieces(p, c)) * v for p, v in values.items() for c in (chess.WHITE, chess.BLACK))


def _phase(ply: int, board_before: chess.Board, in_book: bool) -> Phase:
    if _material(board_before) <= 26:
        return "endgame"
    if in_book or ply < 20:
        return "opening"
    return "middlegame"


def _validated_pv(board: chess.Board, pv: list[str]) -> list[str]:
    """Keeps the legal prefix of the engine line (a tampered or stale line is cut off, not trusted)."""
    out: list[str] = []
    b = board.copy(stack=False)
    for uci in pv[:MAX_PV]:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in b.legal_moves:
            break
        out.append(uci)
        b.push(move)
    return out


def review_game(
    moves: list[str],
    lines: list[EngineLine],
    *,
    initial_fen: str | None = None,
    accuracy_scale: float = 1.0,
) -> dict[str, Any]:
    if len(lines) != len(moves) + 1:
        raise AppError("Expected one evaluation per position (moves + 1).", code="bad_review")

    board = chess.Board(initial_fen or chess.STARTING_FEN)
    book = book_plies(moves) if not initial_fen else set()
    evals: list[int] = []
    reviewed: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {
        "white": dict.fromkeys(CLASSES, 0),
        "black": dict.fromkeys(CLASSES, 0),
    }
    phase_acc: dict[str, dict[str, list[float]]] = {
        "white": {"opening": [], "middlegame": [], "endgame": []},
        "black": {"opening": [], "middlegame": [], "endgame": []},
    }

    # First pass: evaluation per position. Finished positions are scored by the rules,
    # not by whatever the client sent.
    boards: list[chess.Board] = []
    for i in range(len(moves) + 1):
        boards.append(board.copy(stack=False))
        if i < len(moves):
            try:
                move = chess.Move.from_uci(moves[i])
            except ValueError as exc:
                raise AppError("Game contains an invalid move.", code="bad_review") from exc
            if move not in board.legal_moves:
                raise AppError("Game contains an illegal move.", code="bad_review")
            board.push(move)
    for i, b in enumerate(boards):
        if b.is_checkmate():
            evals.append(-MATE_CP if b.turn == chess.WHITE else MATE_CP)
        elif b.is_stalemate() or b.is_insufficient_material():
            evals.append(0)
        else:
            evals.append(lines[i].as_cp())

    for i, uci in enumerate(moves):
        b = boards[i]
        white = b.turn == chess.WHITE
        side = "white" if white else "black"
        move = chess.Move.from_uci(uci)
        san = b.san(move)
        before, after = evals[i], evals[i + 1]
        w_before = win_percent(before) if white else 100 - win_percent(before)
        w_after = win_percent(after) if white else 100 - win_percent(after)
        drop = max(0.0, w_before - w_after)

        line = lines[i]
        # The principal variation should start with the engine's best move; if it
        # doesn't (or is missing), fall back to the best move alone.
        if line.pv and (line.best is None or line.pv[0] == line.best):
            candidate = line.pv
        else:
            candidate = [line.best] if line.best else []
        pv = _validated_pv(b, candidate)
        best = pv[0] if pv else None
        best_san = b.san(chess.Move.from_uci(best)) if best else None

        mover_before = before if white else -before
        mover_after = after if white else -after
        keeps_fastest_mate = mover_before >= MATE_THRESHOLD and mover_after >= mover_before
        played_best = uci == best or san.endswith("#") or keeps_fastest_mate

        if b.legal_moves.count() == 1:
            cls: MoveClass = "forced"
        elif i in book and drop < 5:
            cls = "book"
        else:
            cls = classify(drop, played_best)
        acc = move_accuracy(w_before, w_after)
        counts[side][cls] += 1
        phase_acc[side][_phase(i, b, i in book)].append(acc)
        reviewed.append(
            {
                "ply": i,
                "uci": uci,
                "san": san,
                "class": cls,
                "best": best,
                "best_san": best_san,
                "pv": pv,
                "cp_before": before,
                "cp_after": after,
                "win_drop": round(drop, 2),
                "accuracy": round(acc, 1),
            }
        )

    acc_white, acc_black = game_accuracy(evals, accuracy_scale)
    opening = identify(moves, initial_fen)

    def phase_summary(side: str) -> dict[str, float | None]:
        return {p: (round(sum(v) / len(v), 1) if v else None) for p, v in phase_acc[side].items()}

    return {
        "moves": reviewed,
        "evals": evals,
        "accuracy": {"white": acc_white, "black": acc_black},
        "counts": counts,
        "phases": {"white": phase_summary("white"), "black": phase_summary("black")},
        "opening": {"eco": opening.eco, "name": opening.name} if opening else None,
    }
