"""Rate limits.

* HTTP: counters in Redis, so the limit holds across all server instances
  (an attacker can't dodge it by hitting a different server).
* WebSocket: an in-memory token bucket per connection. Messages arrive many
  times a second during a game; asking Redis about each one would be slow and
  would burn through a free Redis plan's command budget.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from ..errors import RateLimited
from ..redis_client import run_script


async def hit(key: str, limit: int, window_s: int) -> None:
    """Counts one request against `key`; raises RateLimited when over the limit."""
    allowed, ttl_ms = await run_script("rate_limit", [f"rl:{key}"], [limit, window_s * 1000])
    if not int(allowed):
        raise RateLimited(retry_after=max(1, math.ceil(int(ttl_ms) / 1000)))


@dataclass(slots=True)
class TokenBucket:
    """Allows short bursts (capacity) but only `rate` messages per second on average."""

    capacity: float
    rate: float
    tokens: float = field(init=False)
    updated: float = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = self.capacity
        self.updated = time.monotonic()

    def take(self, cost: float = 1.0) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens < cost:
            return False
        self.tokens -= cost
        return True
