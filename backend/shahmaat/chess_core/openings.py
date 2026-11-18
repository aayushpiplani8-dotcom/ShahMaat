"""Opening names (ECO codes) from the Lichess chess-openings dataset (CC0).

The data file maps a position (EPD: board + side to move + castling + en passant,
without move counters) to its opening. Looking positions up instead of move
sequences means transpositions are recognised: 1.d4 Nf6 2.c4 e6 and
1.c4 e6 2.d4 Nf6 both reach the same named opening.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

import chess


@dataclass(frozen=True, slots=True)
class Opening:
    eco: str
    name: str
    ply: int  # how many moves into the game this name was last confirmed


@lru_cache(maxsize=1)
def _book() -> dict[str, tuple[str, str]]:
    raw = resources.files("shahmaat.data").joinpath("openings.json.gz").read_bytes()
    data: dict[str, list[str]] = json.loads(gzip.decompress(raw))
    return {epd: (v[0], v[1]) for epd, v in data.items()}


def identify(moves: list[str], initial_fen: str | None = None) -> Opening | None:
    """Deepest named position reached in the game (stops looking after 40 plies)."""
    if initial_fen and initial_fen != chess.STARTING_FEN:
        return None
    book = _book()
    board = chess.Board()
    found: Opening | None = None
    for ply, uci in enumerate(moves[:40], start=1):
        board.push(chess.Move.from_uci(uci))
        hit = book.get(board.epd())
        if hit:
            found = Opening(eco=hit[0], name=hit[1], ply=ply)
    return found


def book_plies(moves: list[str]) -> set[int]:
    """0-based indexes of moves that land in a named opening position ("book" moves in a review)."""
    book = _book()
    board = chess.Board()
    plies: set[int] = set()
    for i, uci in enumerate(moves[:40]):
        board.push(chess.Move.from_uci(uci))
        if board.epd() in book:
            plies.add(i)
        else:
            break  # once a game leaves theory, later transpositions back don't count as "book"
    return plies
