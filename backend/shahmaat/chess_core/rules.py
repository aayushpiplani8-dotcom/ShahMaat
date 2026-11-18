"""Chess rules, delegated to python-chess (never hand-roll move generation).

python-chess knows legal moves, check, checkmate, stalemate, castling rights,
en passant, promotion, threefold repetition, the 50-move rule and insufficient
material. This module wraps it in the small vocabulary the game service needs.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import chess
import chess.pgn

from ..errors import IllegalAction

STANDARD_FEN = chess.STARTING_FEN


@dataclass(frozen=True, slots=True)
class Outcome:
    result: str  # "1-0" | "0-1" | "1/2-1/2"
    termination: str


def board_from_moves(moves: list[str], initial_fen: str | None = None) -> chess.Board:
    board = chess.Board(initial_fen or STANDARD_FEN)
    for uci in moves:
        board.push(chess.Move.from_uci(uci))
    return board


def parse_move(board: chess.Board, uci: str) -> chess.Move:
    """Validates a UCI move ("e2e4", "e7e8q") against the position. Raises IllegalAction."""
    try:
        move = chess.Move.from_uci(uci)
    except ValueError as exc:
        raise IllegalAction("That isn't a move.") from exc
    if move not in board.legal_moves:
        # A pawn reaching the last rank without a promotion piece: default to a queen
        # only if that is legal; otherwise it's simply illegal.
        if move.promotion is None:
            queen = chess.Move(move.from_square, move.to_square, promotion=chess.QUEEN)
            if queen in board.legal_moves:
                return queen
        raise IllegalAction("Illegal move.")
    return move


def automatic_outcome(board: chess.Board) -> Outcome | None:
    """Game-ending conditions that apply without anyone claiming them.

    Threefold repetition and the 50-move rule end the game automatically here (as
    on most online sites) instead of needing a claim, which keeps the protocol small.
    """
    if board.is_checkmate():
        return Outcome("0-1" if board.turn == chess.WHITE else "1-0", "checkmate")
    if board.is_stalemate():
        return Outcome("1/2-1/2", "stalemate")
    if board.is_insufficient_material():
        return Outcome("1/2-1/2", "insufficient_material")
    if board.can_claim_threefold_repetition():
        return Outcome("1/2-1/2", "repetition")
    if board.can_claim_fifty_moves():
        return Outcome("1/2-1/2", "fifty_moves")
    return None


def timeout_outcome(board: chess.Board, flagged_white: bool) -> Outcome:
    """Running out of time loses, unless the opponent can't possibly checkmate (FIDE 6.9)."""
    winner = chess.BLACK if flagged_white else chess.WHITE
    if board.has_insufficient_material(winner):
        return Outcome("1/2-1/2", "timeout_vs_insufficient")
    return Outcome("0-1" if flagged_white else "1-0", "timeout")


def san_list(moves: list[str], initial_fen: str | None = None) -> list[str]:
    board = chess.Board(initial_fen or STANDARD_FEN)
    out: list[str] = []
    for uci in moves:
        move = chess.Move.from_uci(uci)
        out.append(board.san(move))
        board.push(move)
    return out


def parse_pgn(pgn: str) -> tuple[chess.pgn.Game, list[str]]:
    """Parses one PGN game; returns the game object and its mainline as UCI moves."""
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None or game.errors:
        raise IllegalAction("Couldn't read that PGN.")
    return game, [m.uci() for m in game.mainline_moves()]


def to_pgn(
    moves: list[str],
    headers: dict[str, str],
    initial_fen: str | None = None,
    clocks_ms: list[int] | None = None,
) -> str:
    game = chess.pgn.Game()
    for key, value in headers.items():
        game.headers[key] = value
    if initial_fen and initial_fen != STANDARD_FEN:
        game.setup(initial_fen)
    node: chess.pgn.GameNode = game
    for i, uci in enumerate(moves):
        node = node.add_variation(chess.Move.from_uci(uci))
        if clocks_ms and i < len(clocks_ms):
            node.set_clock(clocks_ms[i] / 1000)
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=True)
    return game.accept(exporter)
