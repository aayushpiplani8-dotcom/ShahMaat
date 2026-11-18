"""Chess clock maths. Pure functions: no Redis, no network, no real time.

The server is the only timekeeper. A player's browser shows a countdown, but the
number that counts is computed here from server timestamps. Every function takes
`now_ms` as an argument, which makes them trivial to test with a fake clock.

Rules implemented:
* The clock of the side to move runs from `turn_started_ms`.
* Neither clock runs before each side has made its first move (like most sites).
  Instead, each side gets FIRST_MOVE_MS to make that move or the game is aborted.
* Lag compensation: up to MAX_LAG_COMP_MS of the player's measured network delay
  is given back on each move, so a slow connection doesn't eat a bullet player's time.
* Increment (Fischer) is added after the move, only if the player hadn't flagged.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

FIRST_MOVE_MS = 30_000
MAX_LAG_COMP_MS = 300


@dataclass(slots=True)
class ClockState:
    white_ms: int
    black_ms: int
    turn_started_ms: int  # when the side to move started thinking (server time)

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, int]) -> ClockState:
        return cls(
            white_ms=int(d["white_ms"]),
            black_ms=int(d["black_ms"]),
            turn_started_ms=int(d["turn_started_ms"]),
        )


def clock_running(ply: int) -> bool:
    """Clocks start only after both players' first moves (ply = moves made so far)."""
    return ply >= 2


def remaining_ms(clock: ClockState, white_to_move: bool, ply: int, now_ms: int) -> tuple[int, int]:
    """(white_ms, black_ms) as of now, counting down the side to move."""
    white, black = clock.white_ms, clock.black_ms
    if clock_running(ply):
        elapsed = max(0, now_ms - clock.turn_started_ms)
        if white_to_move:
            white -= elapsed
        else:
            black -= elapsed
    return max(0, white), max(0, black)


@dataclass(slots=True, frozen=True)
class MoveTiming:
    clock: ClockState
    flagged: bool  # the mover was already out of time when the move arrived
    mover_left_ms: int  # the mover's time after the move (for the move-time chart)


def apply_move(
    clock: ClockState,
    *,
    white_moved: bool,
    ply_before: int,
    now_ms: int,
    increment_ms: int,
    lag_ms: int = 0,
) -> MoveTiming:
    """Charges the mover for the time they used and starts the opponent's clock."""
    white, black = clock.white_ms, clock.black_ms
    mover = white if white_moved else black

    if clock_running(ply_before):
        used = max(0, now_ms - clock.turn_started_ms - min(max(lag_ms, 0), MAX_LAG_COMP_MS))
        mover -= used
        if mover <= 0:
            flagged_clock = ClockState(
                white_ms=0 if white_moved else white,
                black_ms=black if white_moved else 0,
                turn_started_ms=clock.turn_started_ms,
            )
            return MoveTiming(clock=flagged_clock, flagged=True, mover_left_ms=0)
        mover += increment_ms

    new = ClockState(
        white_ms=mover if white_moved else white,
        black_ms=black if white_moved else mover,
        turn_started_ms=now_ms,
    )
    return MoveTiming(clock=new, flagged=False, mover_left_ms=mover)


def flag_deadline_ms(clock: ClockState, white_to_move: bool, ply: int) -> int | None:
    """The server time at which the side to move runs out (None while clocks aren't running)."""
    if not clock_running(ply):
        return None
    left = clock.white_ms if white_to_move else clock.black_ms
    return clock.turn_started_ms + left


def first_move_deadline_ms(clock: ClockState, ply: int) -> int | None:
    """Abort deadline while either side still owes its first move."""
    if ply >= 2:
        return None
    return clock.turn_started_ms + FIRST_MOVE_MS
