"""Time controls offered in the lobby.

"3+2" means 3 minutes each plus 2 seconds added after every move.
The time class (bullet / blitz / rapid) decides which rating changes, using the
same rule as most sites: estimated game length = base + 40 x increment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TimeClass = Literal["bullet", "blitz", "rapid"]
TIME_CLASSES: tuple[TimeClass, ...] = ("bullet", "blitz", "rapid")


@dataclass(frozen=True, slots=True)
class TimeControl:
    key: str
    initial_ms: int
    increment_ms: int

    @property
    def time_class(self) -> TimeClass:
        estimate_s = self.initial_ms / 1000 + 40 * self.increment_ms / 1000
        if estimate_s < 180:
            return "bullet"
        if estimate_s < 600:
            return "blitz"
        return "rapid"

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "initial_ms": self.initial_ms,
            "increment_ms": self.increment_ms,
            "time_class": self.time_class,
        }


def _tc(minutes: float, inc: int) -> TimeControl:
    key = f"{int(minutes) if minutes >= 1 else minutes}+{inc}"
    return TimeControl(key=key, initial_ms=int(minutes * 60_000), increment_ms=inc * 1000)


TIME_CONTROLS: dict[str, TimeControl] = {
    tc.key: tc
    for tc in (
        _tc(1, 0),
        _tc(2, 1),
        _tc(3, 0),
        _tc(3, 2),
        _tc(5, 0),
        _tc(5, 3),
        _tc(10, 0),
        _tc(10, 5),
        _tc(15, 10),
        _tc(30, 0),
    )
}


def get_time_control(key: str) -> TimeControl | None:
    return TIME_CONTROLS.get(key)


def key_for(initial_ms: int, increment_ms: int) -> str:
    for tc in TIME_CONTROLS.values():
        if tc.initial_ms == initial_ms and tc.increment_ms == increment_ms:
            return tc.key
    minutes = initial_ms / 60_000
    return f"{int(minutes) if minutes.is_integer() else round(minutes, 2)}+{increment_ms // 1000}"
