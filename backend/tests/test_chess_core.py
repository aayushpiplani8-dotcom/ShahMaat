"""Pure logic: Glicko-2, clocks, rules, review maths, puzzles. No database needed."""

from __future__ import annotations

from datetime import UTC, datetime

import chess
import pytest

from shahmaat.chess_core import glicko2, puzzles
from shahmaat.chess_core.clock import (
    FIRST_MOVE_MS,
    MAX_LAG_COMP_MS,
    ClockState,
    apply_move,
    first_move_deadline_ms,
    flag_deadline_ms,
    remaining_ms,
)
from shahmaat.chess_core.openings import identify
from shahmaat.chess_core.review import (
    EngineLine,
    classify,
    game_accuracy,
    move_accuracy,
    review_game,
    win_percent,
)
from shahmaat.chess_core.rules import automatic_outcome, board_from_moves, parse_move, timeout_outcome
from shahmaat.chess_core.timecontrols import TIME_CONTROLS
from shahmaat.errors import AppError, IllegalAction

# ------------------------------------------------------------------ Glicko-2


def test_glicko2_matches_glickmans_worked_example() -> None:
    """The example from section 'Example of the Glicko-2 system' in Glickman's paper."""
    player = glicko2.Glicko(1500, 200, 0.06)
    results = [
        (glicko2.Glicko(1400, 30, 0.06), 1.0),
        (glicko2.Glicko(1550, 100, 0.06), 0.0),
        (glicko2.Glicko(1700, 300, 0.06), 0.0),
    ]
    new = glicko2.update(player, results)
    assert new.rating == pytest.approx(1464.06, abs=0.01)
    assert new.rd == pytest.approx(151.52, abs=0.01)
    assert new.volatility == pytest.approx(0.05999, abs=1e-5)


def test_glicko2_is_zero_sum_for_equal_players() -> None:
    w, b = glicko2.rate_game(glicko2.Glicko(), glicko2.Glicko(), 1.0)
    assert w.rating > 1500 > b.rating
    assert w.rating - 1500 == pytest.approx(1500 - b.rating, abs=1e-6)
    assert w.rd < 350 and b.rd < 350  # one game makes us more certain


def test_upset_moves_ratings_more_than_expected_result() -> None:
    strong, weak = glicko2.Glicko(1900, 60), glicko2.Glicko(1500, 60)
    expected_win, _ = glicko2.rate_game(strong, weak, 1.0)
    upset_loss, _ = glicko2.rate_game(strong, weak, 0.0)
    assert abs(upset_loss.rating - 1900) > abs(expected_win.rating - 1900) * 3


# -------------------------------------------------------------------- clocks


def test_clocks_do_not_run_before_both_first_moves() -> None:
    clock = ClockState(60_000, 60_000, turn_started_ms=0)
    after_white = apply_move(clock, white_moved=True, ply_before=0, now_ms=20_000, increment_ms=2000)
    assert after_white.clock.white_ms == 60_000  # no time charged, no increment
    assert first_move_deadline_ms(after_white.clock, 1) == 20_000 + FIRST_MOVE_MS
    assert flag_deadline_ms(after_white.clock, False, 1) is None


def test_time_is_charged_and_increment_added() -> None:
    clock = ClockState(60_000, 60_000, turn_started_ms=1_000)
    t = apply_move(clock, white_moved=True, ply_before=2, now_ms=11_000, increment_ms=2_000)
    assert t.clock.white_ms == 60_000 - 10_000 + 2_000
    assert t.clock.black_ms == 60_000
    assert t.clock.turn_started_ms == 11_000
    assert not t.flagged


def test_late_move_flags_instead_of_counting() -> None:
    clock = ClockState(5_000, 60_000, turn_started_ms=0)
    t = apply_move(clock, white_moved=True, ply_before=4, now_ms=6_000, increment_ms=2_000)
    assert t.flagged and t.clock.white_ms == 0


def test_lag_compensation_is_capped() -> None:
    clock = ClockState(60_000, 60_000, turn_started_ms=0)
    fair = apply_move(clock, white_moved=True, ply_before=2, now_ms=1_000, increment_ms=0, lag_ms=100)
    greedy = apply_move(clock, white_moved=True, ply_before=2, now_ms=1_000, increment_ms=0, lag_ms=10_000)
    assert fair.clock.white_ms == 59_100
    assert greedy.clock.white_ms == 60_000 - 1_000 + MAX_LAG_COMP_MS


def test_remaining_counts_down_only_the_side_to_move() -> None:
    clock = ClockState(30_000, 30_000, turn_started_ms=10_000)
    assert remaining_ms(clock, True, 2, 15_000) == (25_000, 30_000)
    assert remaining_ms(clock, False, 3, 15_000) == (30_000, 25_000)
    assert flag_deadline_ms(clock, True, 2) == 40_000


def test_time_classes() -> None:
    assert TIME_CONTROLS["1+0"].time_class == "bullet"
    assert TIME_CONTROLS["2+1"].time_class == "bullet"
    assert TIME_CONTROLS["3+2"].time_class == "blitz"
    assert TIME_CONTROLS["10+0"].time_class == "rapid"


# --------------------------------------------------------------------- rules


def test_illegal_and_malformed_moves_are_rejected() -> None:
    board = chess.Board()
    with pytest.raises(IllegalAction):
        parse_move(board, "e2e5")
    with pytest.raises(IllegalAction):
        parse_move(board, "zz99")


def test_promotion_defaults_to_queen() -> None:
    board = chess.Board("8/P7/8/8/8/8/8/k6K w - - 0 1")
    assert parse_move(board, "a7a8").promotion == chess.QUEEN


def test_checkmate_and_threefold_end_the_game() -> None:
    mate = board_from_moves(["f2f3", "e7e5", "g2g4", "d8h4"])
    assert automatic_outcome(mate) is not None and automatic_outcome(mate).termination == "checkmate"  # type: ignore[union-attr]
    shuffle = ["g1f3", "g8f6", "f3g1", "f6g8"] * 2
    outcome = automatic_outcome(board_from_moves(shuffle))
    assert outcome is not None and outcome.termination == "repetition"


def test_timeout_against_lone_king_is_a_draw() -> None:
    board = chess.Board("8/8/8/4k3/8/8/8/4K2Q b - - 0 1")
    # Black flags, but White (Q) can mate: white wins.
    assert timeout_outcome(board, flagged_white=False).result == "1-0"
    # White flags, and Black has a bare king: draw.
    assert timeout_outcome(board, flagged_white=True).result == "1/2-1/2"


def test_opening_names_follow_transpositions() -> None:
    a = identify(["d2d4", "d7d5", "c2c4", "e7e6"])
    b = identify(["c2c4", "e7e6", "d2d4", "d7d5"])
    assert a is not None and b is not None
    assert a.name == b.name == "Queen's Gambit Declined"
    najdorf = identify(["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "a7a6"])
    assert najdorf is not None and najdorf.eco == "B90"


# -------------------------------------------------------------------- review


def test_win_percent_and_accuracy_curves() -> None:
    assert win_percent(0) == pytest.approx(50)
    assert win_percent(300) > 75 > win_percent(-300) + 50
    assert move_accuracy(60, 60) == 100
    assert move_accuracy(60, 20) < move_accuracy(60, 50) < 100


def test_classification_thresholds() -> None:
    assert classify(0, True) == "best"
    assert classify(1, False) == "excellent"
    assert classify(7, False) == "inaccuracy"
    assert classify(15, False) == "mistake"
    assert classify(40, False) == "blunder"


def test_flawless_game_scores_100() -> None:
    assert game_accuracy([20] * 41) == (100.0, 100.0)


def _line(cp: int, best: str | None = None, pv: list[str] | None = None) -> EngineLine:
    return EngineLine(cp=cp, mate=None, best=best, pv=pv or ([best] if best else []))


def test_review_finds_the_blunder_and_ignores_illegal_engine_moves() -> None:
    moves = ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"]
    lines = [
        _line(30, "e2e4"),
        _line(30, "e7e5"),
        _line(40, "g1f3"),
        _line(10, "b8c6"),
        _line(60, "f1c4"),
        _line(60, "g7g6"),  # Nf6?? allows mate; engine wanted g6
        _line(10_000, "h5f7"),
        _line(10_000, "a1a8"),  # illegal "engine" move from a tampered client: dropped
    ]
    review = review_game(moves, lines)
    nf6 = review["moves"][5]
    assert nf6["san"] == "Nf6" and nf6["class"] == "blunder"
    assert nf6["best_san"] == "g6"
    qxf7 = review["moves"][6]
    assert qxf7["san"] == "Qxf7#" and qxf7["class"] in ("best", "book")
    assert review["evals"][-1] == 10_000  # mate scored by the rules, not the client
    assert review["accuracy"]["white"] > review["accuracy"]["black"]
    assert review["moves"][0]["class"] == "book"


def test_review_rejects_mismatched_lengths_and_illegal_games() -> None:
    with pytest.raises(AppError):
        review_game(["e2e4"], [_line(0)])
    with pytest.raises(AppError):
        review_game(["e2e5"], [_line(0), _line(0)])


# ------------------------------------------------------------------- puzzles


def test_puzzles_come_from_the_players_own_mistakes() -> None:
    moves = ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"]
    lines = [
        _line(30),
        _line(30),
        _line(40),
        _line(10),
        _line(60),
        _line(60, "g7g6"),
        _line(10_000),
        _line(10_000),
    ]
    review = review_game(moves, lines)
    seeds_black = puzzles.extract(review, moves, player_is_white=False)
    assert [s.ply for s in seeds_black] == [5]
    assert seeds_black[0].solution[0] == "g7g6"
    assert puzzles.extract(review, moves, player_is_white=True) == []


def test_any_mating_move_solves_a_puzzle() -> None:
    fen = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"
    assert puzzles.is_correct(fen, ["a1a8"], "a1a8")
    assert not puzzles.is_correct(fen, ["a1a8"], "a1a7")


def test_spaced_repetition_schedule() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    box, due = puzzles.schedule(0, True, now)
    assert box == 1 and (due - now).days == 1
    box, due = puzzles.schedule(3, True, now)
    assert box == 4 and (due - now).days == 21
    box, due = puzzles.schedule(4, False, now)
    assert box == 0 and (due - now).total_seconds() == 3600
