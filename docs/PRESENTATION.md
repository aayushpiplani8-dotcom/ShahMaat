# Presenting ShahMaat

A guide to explaining this project in an interview, a viva or a demo. Read it alongside
the code: every claim below points to a file you can open and walk through.

---

## The 30-second pitch

> "ShahMaat is a real-time multiplayer chess platform I built with FastAPI, React, Postgres
> and Redis. Players get rated games with server-run clocks, and every game can be reviewed
> by Stockfish for free. The engine runs in the browser as WebAssembly, so analysis costs
> the server nothing. The hard parts were on the backend: making the server the only source
> of truth, handling races like a move and a timeout arriving at the same instant, and
> keeping games alive across server restarts. It's tested against real Postgres and Redis,
> runs in Docker, and deploys for free on Render."

## The 3-minute walkthrough

1. **What it does** (show the home page): rated matchmaking, live games, review, puzzles from your own mistakes.
2. **Architecture** (show the diagram in the README): React ↔ FastAPI over REST + WebSockets;
   Redis holds live games, Postgres holds finished ones.
3. **One move, end to end** (open `game/service.py`, method `move`): the browser asks, the server
   checks turn and legality and charges the clock, then compare-and-set saves it and everyone gets a snapshot.
4. **One hard problem** (pick one from the deep dives below; races are the best story).
5. **Quality**: 52 backend tests including race and restart tests, CI, Docker, security headers, rate limits.

## Demo script (5 minutes)

1. Open the site in two browsers (one normal, one private window) and sign up as two users.
2. Both click **3+2** and the game starts. Make a few moves and point out the clocks.
3. **Premove:** while it's your opponent's turn, make your next move. It plays the moment their move lands.
4. **Refresh the page mid-game.** It reconnects and the game continues. (State lives in Redis, not in the page.)
5. Open the game in a third tab while signed out. That's spectator mode.
6. Offer a draw, or resign, and show the rating change (Glicko-2).
7. Click **Review game**, then **Fast**. Show the labels, accuracy by phase, the eval graph, and "best was …".
8. Open **Puzzles**: your blunder is now a puzzle.
9. Optional: **Import** a chess.com username and review one of those games.

---

## Deep dives (explained simply)

### 1. "The server is the referee"
The browser can be modified by anyone, so it's never trusted. It only sends *requests*
like "I want to play e2e4 in position 12". The server:
- finds the player from their **token**, never from the message (`realtime/endpoint.py`)
- checks it's their turn and that the move is legal, using python-chess
- works out how much time they used **from its own clock** (`chess_core/clock.py`)
- decides whether the game is over (checkmate, repetition, flag-fall)

**Interview line:** "Clients send intents, the server owns the state. That one rule
prevents most cheating and most desync bugs."

### 2. Race conditions: optimistic locking with Redis Lua
**Problem:** say both players resign at the same millisecond, or a move arrives just as the
clock runs out. Two requests read the same game and both try to save, so two results
(or double rating changes) could appear.

**Solution** (`game/store.py`, `redis_client.py` → `CAS_GAME`):
- Every game has a version number.
- To change a game: read it (state + version), compute the change, then save **only if the
  version is still the same**. That check-and-save is one Lua script, and Redis runs a Lua
  script as one indivisible step.
- If someone else saved first, the script refuses and we recompute from the fresh state.

It's called *optimistic* locking because nothing is locked while we think, so a slow
request never blocks a fast one. There's a test for exactly this:
`tests/test_referee.py::test_simultaneous_resignations_produce_one_result`.

**Why not a database lock?** Moves happen many times a second. An in-memory Redis
compare-and-set takes about 1 ms and needs no lock to be released if a server crashes mid-way.

### 3. Timers that survive crashes (`game/timers.py`)
A flag must fall even if nobody sends a message. There are three layers:
1. **Redis sorted set** `timers` (game id → deadline). This is durable, so a restarted server knows every deadline.
2. **asyncio timer in memory** on each server, so the flag falls within milliseconds without polling.
3. **A sweeper** every 60 s that asks Redis "anything overdue?", in case a timer was lost.

If a timer fires twice, nothing breaks: the referee re-checks under compare-and-set, so only one "game over" is ever saved.

### 4. Saving a finished game exactly once (`game/archive.py`)
- The game row and both rating updates happen in **one Postgres transaction**: all or nothing.
- The insert uses `ON CONFLICT DO NOTHING` on the game id, so running it twice (a retry,
  two servers) changes nothing the second time. That property is called *idempotency*.
- Both players' rating rows are locked **in sorted order**. If two games lock rows in
  different orders, they can deadlock; a fixed order makes that impossible.

### 5. Glicko-2 instead of Elo (`chess_core/glicko2.py`)
Elo has one number. Glicko-2 adds:
- **RD (rating deviation):** how *sure* we are. New players start at 350, so early games
  move their rating a lot. As they play, RD shrinks and changes get smaller.
- **Volatility:** how erratic a player's results are.

A rating is "provisional" (shown with `?`) until RD drops below 110. The implementation
reproduces the worked example in Glickman's paper exactly: see
`test_glicko2_matches_glickmans_worked_example`.

### 6. Matchmaking (`game/matchmaking.py`)
- Each time control has a Redis **sorted set** scored by rating.
- You accept opponents within ±75 points, widening by 25 per second you wait (max ±600).
- The pairing is one Lua script. It finds the closest opponent whose **own** window also
  accepts you, then removes both players atomically, so two servers can't hand one player two opponents.
- The retry loop only runs while someone is waiting, so an empty site costs zero Redis commands.

### 7. WebSockets: snapshots, versions, backpressure (`realtime/`)
- **Full snapshots, not diffs.** Every update is the whole game state (a few KB) with a
  version number. A client that missed messages is fixed by the next one, and older
  versions are ignored.
- **Optimistic UI:** your move shows instantly; if the server refuses it, the board snaps back.
- **Backpressure:** each connection has its own outbound queue. If a browser stops reading,
  only that connection is dropped (it reconnects); everyone else's game keeps moving.
- **Validation:** every message is checked by a Pydantic schema. Wrong type, extra field,
  bad move format or anything over 4 KB is rejected before game code runs.
- **Lag compensation:** the server pings every 10 s and gives back up to 300 ms of measured
  network delay per move, so slow connections aren't punished in bullet.

### 8. Scaling to more than one server (`realtime/bus.py`)
One server keeps everything in-process. With `MULTI_INSTANCE=true`, messages go through
**Redis pub/sub**, so a move on server A reaches a spectator on server B. Game state was
already in Redis, so nothing else changes. This was tested by running two servers, playing
a game across them, and letting the clock run out.

### 9. Auth that's hard to steal (`auth/tokens.py`)
- **Access token:** a JWT valid for 15 minutes, kept in JavaScript memory only.
- **Refresh token:** a random string in an `httpOnly` cookie (JavaScript can't read it, so
  XSS can't steal it), `SameSite=Strict` (other sites can't trigger it), sent only to `/api/auth`.
- **Rotation + reuse detection:** every refresh swaps the token for a new one. If an old
  token is ever used again, someone copied it, so the whole login is revoked.
- Refresh tokens are stored as **HMAC hashes**, so a database leak doesn't hand out sessions.

### 10. Review pipeline: browser computes, server scores (`chess_core/review.py`)
- Stockfish in the browser evaluates every position (free for the server, unlimited for users).
- The server replays the game, drops any engine move that isn't legal, scores
  checkmates and stalemates by the rules itself, then computes:
  - **win%** from centipawns (a logistic curve fitted on millions of games)
  - **move accuracy** from the win% lost
  - **game accuracy:** volatility-weighted mean averaged with a harmonic mean, so one
    terrible move counts heavily
  - **phase accuracy** (opening / middlegame / endgame, by material left)
- Reviews are stored and shareable; a deeper review replaces a shallower one.

### 11. Puzzles with spaced repetition (`chess_core/puzzles.py`)
Each of *your* mistakes or blunders (where you weren't already lost) becomes a puzzle.
These are Leitner boxes: solve it and it comes back after 1 → 3 → 7 → 21 → 60 days; fail
and it returns in an hour. The answer is never sent to the browser; the server checks your
move, and any checkmating move also counts.

---

## Likely questions, with answers

**Why Redis *and* Postgres?**
Live games change many times a second and must be shared between servers, which is Redis's
job (in memory, atomic scripts). Finished games, users and ratings need durability,
relations and transactions, which is Postgres's job. Each game is written to Postgres once,
when it ends.

**What happens if the server crashes mid-game?**
Game state and deadlines are in Redis, so nothing is lost. The new process re-arms timers
from the sorted set, finishes archiving games that ended during the crash, and browsers
reconnect with exponential backoff and receive a full snapshot. There's a test that does
exactly this (`test_game_survives_a_server_restart`).

**What if Redis goes down?**
Live play pauses (honestly). Finished games, accounts and reviews are in Postgres and stay
safe. On Upstash, Redis is replicated by the provider. For self-hosting, Redis runs with AOF
persistence in `docker-compose.yml`.

**How do you stop cheating?**
The server validates everything, so you can't make illegal moves or fake the clock. Engine
review is refused while a game is in progress. Detecting someone using an engine on a second
device is unsolved in general; that's listed as a known limit.

**Why does Stockfish run in the browser?**
Cost and scale. A free-tier server has a fraction of one CPU; analysing a game there would
take minutes and block other players. The user's own CPU is free, fast and scales with the
number of users. The server still owns the *scoring*, so results are consistent.

**How do clocks stay in sync between two browsers?**
They don't need to: the server's clock is the truth. Each snapshot carries the time left as
of the server's "now". The browser counts down locally from the moment it received it, using
`performance.now()`, so even a wrong system clock on the user's PC doesn't matter.

**What's the hardest bug you hit?**
(Pick one you understand well.) For example: a move arriving after the flag fell. The fix
was to charge the clock *before* applying the move, and if the time had already run out, end
the game on time instead of playing the move (`test_late_move_loses_on_time_even_if_legal`).

**How would you scale to 100,000 players?**
Run several app instances behind a load balancer with `MULTI_INSTANCE=true` (already
supported). Shard live games across a Redis cluster by game id (each game touches one key).
Add Postgres read replicas for profiles and leaderboards, and move chess.com fetching to a
background worker queue.

**How is it tested?**
52 backend tests against real Postgres and Redis (no mocks for the things that break in
production), plus frontend unit tests. CI runs lint, type checks, tests, a dependency audit
and a Docker build on every push. Full browser runs were done with Playwright: two players
matched, premoves, reload mid-game, spectating, draw, review and puzzles.

---

## Numbers to remember

- ~5,300 lines of Python, ~3,900 lines of React/JS, 52 backend tests + 10 frontend tests
- Move handling: one Redis read and one atomic Lua write per move, about 1 ms
- Rating window: ±75, +25/s, max ±600
- Lag compensation: up to 300 ms per move; first-move timeout: 30 s; disconnect claim: 30 s
- Access token 15 min; refresh token 30 days, rotated on every use
