"""Redis connection and the Lua scripts that run atomically inside Redis.

A Lua script runs as one indivisible step: no other command can sneak in between
its reads and writes. That is how ShahMaat makes "check, then change" operations
safe when two requests race (two moves at once, a move and a timeout, two
players resigning at the same instant).
"""

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis
from redis.commands.core import AsyncScript

_redis: Redis | None = None
_scripts: dict[str, AsyncScript] = {}

# Compare-and-set for live games. KEYS[1] = game hash.
# ARGV: expected version, new version, new state JSON, TTL seconds (0 = keep)
# Returns 1 when saved, 0 when someone else changed the game first.
CAS_GAME = """
local current = redis.call('HGET', KEYS[1], 'v')
if (current or '0') ~= ARGV[1] then
  return 0
end
redis.call('HSET', KEYS[1], 'v', ARGV[2], 'state', ARGV[3])
local ttl = tonumber(ARGV[4])
if ttl and ttl > 0 then
  redis.call('EXPIRE', KEYS[1], ttl)
end
return 1
"""

# Sliding-window-ish fixed window counter. KEYS[1] = counter key. ARGV: limit, window ms.
# Returns {allowed (0/1), ms until the window resets}.
RATE_LIMIT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
local ttl = redis.call('PTTL', KEYS[1])
if n > tonumber(ARGV[1]) then
  return {0, ttl}
end
return {1, ttl}
"""

# Matchmaking pairing. Finds the closest-rated waiting opponent whose rating
# window ALSO accepts us, removes both from the queue and returns the opponent.
# KEYS[1] = queue zset (score = rating), KEYS[2] = meta hash (user -> "rating|joined_ms")
# ARGV: user id, now ms, base window, growth per second, max window
# Returns the opponent id, nil when nobody fits yet, or '__gone__' if we were already paired.
PAIR = """
local me = ARGV[1]
local now = tonumber(ARGV[2])
local base = tonumber(ARGV[3])
local growth = tonumber(ARGV[4])
local maxw = tonumber(ARGV[5])
local mine = redis.call('HGET', KEYS[2], me)
if not mine then return '__gone__' end
local sep = string.find(mine, '|', 1, true)
local my_rating = tonumber(string.sub(mine, 1, sep - 1))
local my_joined = tonumber(string.sub(mine, sep + 1))
local function window(joined)
  local w = base + growth * math.max(0, now - joined) / 1000
  if w > maxw then w = maxw end
  return w
end
local my_w = window(my_joined)
local candidates = redis.call('ZRANGEBYSCORE', KEYS[1], my_rating - my_w, my_rating + my_w)
local best, best_gap = nil, nil
for _, other in ipairs(candidates) do
  if other ~= me then
    local meta = redis.call('HGET', KEYS[2], other)
    if meta then
      local s = string.find(meta, '|', 1, true)
      local r = tonumber(string.sub(meta, 1, s - 1))
      local j = tonumber(string.sub(meta, s + 1))
      local gap = math.abs(r - my_rating)
      if gap <= window(j) and (best_gap == nil or gap < best_gap) then
        best, best_gap = other, gap
      end
    end
  end
end
if not best then return false end
redis.call('ZREM', KEYS[1], me, best)
redis.call('HDEL', KEYS[2], me, best)
return best
"""

# Take a value only if it still equals the expected one (release-if-owner).
DELETE_IF_EQUALS = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


async def init_redis(url: str) -> Redis:
    global _redis
    _redis = Redis.from_url(
        url,
        decode_responses=True,
        health_check_interval=30,
        socket_keepalive=True,
        retry_on_timeout=True,
    )
    _scripts.clear()
    for name, body in {
        "cas_game": CAS_GAME,
        "rate_limit": RATE_LIMIT,
        "pair": PAIR,
        "delete_if_equals": DELETE_IF_EQUALS,
    }.items():
        _scripts[name] = _redis.register_script(body)
    return _redis


def redis() -> Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialised")
    return _redis


async def run_script(name: str, keys: list[str], args: list[Any]) -> Any:
    return await _scripts[name](keys=keys, args=args)


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None
