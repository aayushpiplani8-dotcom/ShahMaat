"""The referee. Every change to a live game goes through this class.

Golden rule: the browser only ASKS. It sends "I'd like to play e2e4"; the server
checks whose turn it is, whether the move is legal (python-chess), how much time
the player really used (server clock), and whether the game is now over. Then it
saves the new state with compare-and-set and tells everyone watching.

Every public method follows the same pattern:
    store.mutate(game_id, change)  -> atomic, retried on conflicts
    self._after_change(game)       -> timers, archiving, broadcast
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from ..chess_core.clock import ClockState, apply_move, first_move_deadline_ms, flag_deadline_ms, remaining_ms
from ..chess_core.glicko2 import is_provisional
from ..chess_core.openings import identify
from ..chess_core.rules import Outcome, automatic_outcome, board_from_moves, parse_move, timeout_outcome
from ..chess_core.timecontrols import TimeControl
from ..db import session_scope
from ..db.models import Rating, User
from ..errors import Forbidden, IllegalAction, NotFound
from ..metrics import GAMES_FINISHED, GAMES_STARTED, MOVE_LATENCY, MOVES
from ..redis_client import redis
from . import store
from .archive import archive_game
from .state import CLAIM_AFTER_MS, Color, LiveGame, Player, new_game_id, other
from .store import NoChange
from .timers import TimerScheduler

log = structlog.get_logger("shahmaat.referee")
Publish = Callable[[str, dict[str, Any]], Awaitable[None]]


def now_ms() -> int:
    return int(time.time() * 1000)


def game_channel(game_id: str) -> str:
    return f"game:{game_id}"


def user_channel(user_id: str) -> str:
    return f"user:{user_id}"


async def load_player(user_id: str, time_class: str) -> Player:
    async with session_scope() as db:
        user = await db.get(User, uuid.UUID(user_id))
        rating = await db.get(Rating, (uuid.UUID(user_id), time_class))
    if user is None or rating is None:
        raise NotFound("Player not found.")
    return Player(
        id=user_id, username=user.username, rating=round(rating.rating), provisional=is_provisional(rating.rd)
    )


class GameService:
    def __init__(self, publish: Publish, timers: TimerScheduler) -> None:
        self._publish = publish
        self._timers = timers

    # ------------------------------------------------------------------ create
    async def ensure_free(self, user_id: str) -> None:
        """Refuses if the user is already playing. Cleans up stale pointers left by crashes."""
        game_id = await store.active_game_of(user_id)
        if not game_id:
            return
        loaded = await store.load(game_id)
        if loaded and loaded[0].status == "active":
            raise IllegalAction("You're already in a game.", code="already_playing")
        if loaded:
            await store.finish_bookkeeping(loaded[0])
        else:
            await redis().delete(store.user_game_key(user_id))

    async def create_game(
        self,
        white_id: str,
        black_id: str,
        tc: TimeControl,
        *,
        rated: bool,
        source: str,
        game_id: str | None = None,
    ) -> LiveGame:
        if white_id == black_id:
            raise IllegalAction("You can't play yourself.")
        white = await load_player(white_id, tc.time_class)
        black = await load_player(black_id, tc.time_class)
        now = now_ms()
        game = LiveGame(
            id=game_id or new_game_id(),
            white=white,
            black=black,
            tc_key=tc.key,
            initial_ms=tc.initial_ms,
            increment_ms=tc.increment_ms,
            time_class=tc.time_class,
            rated=rated,
            source=source,
            clock=ClockState(white_ms=tc.initial_ms, black_ms=tc.initial_ms, turn_started_ms=now),
            created_ms=now,
        )
        await store.create(game)
        GAMES_STARTED.labels(tc.time_class, source).inc()
        log.info(
            "game_started",
            game_id=game.id,
            white=white.username,
            black=black.username,
            tc=tc.key,
            rated=rated,
        )
        await self._after_change(game, 1)
        for uid in (white_id, black_id):
            await self._publish(user_channel(uid), {"type": "match.found", "game_id": game.id})
        return game

    async def notify_user(self, user_id: str, message: dict[str, Any]) -> None:
        await self._publish(user_channel(user_id), message)

    # ------------------------------------------------------------------ reads
    async def snapshot(self, game_id: str) -> dict[str, Any] | None:
        loaded = await store.load(game_id)
        if loaded is None:
            return None
        game, version = loaded
        return game.snapshot(now_ms(), version)

    # ---------------------------------------------------------------- actions
    async def move(
        self, user_id: str, game_id: str, uci: str, expected_ply: int | None, lag_ms: int = 0
    ) -> None:
        started = time.perf_counter()

        def change(g: LiveGame) -> None:
            color = self._require_turn_player(g, user_id)
            if expected_ply is not None and expected_ply != g.ply:
                raise IllegalAction("That move was for an older position.", code="stale_move")
            board = board_from_moves(g.moves)
            move = parse_move(board, uci)
            now = now_ms()
            timing = apply_move(
                g.clock,
                white_moved=color == "white",
                ply_before=g.ply,
                now_ms=now,
                increment_ms=g.increment_ms,
                lag_ms=lag_ms,
            )
            if timing.flagged:
                # The move arrived after the flag fell: the clock decides, not the move.
                g.clock = timing.clock
                self._end(g, timeout_outcome(board, flagged_white=color == "white"), now, freeze=False)
                return
            g.san.append(board.san(move))
            board.push(move)
            g.moves.append(move.uci())
            g.clocks_ms.append(timing.mover_left_ms)
            g.clock = timing.clock
            g.fen = board.fen()
            if g.draw_offer == other(color):
                g.draw_offer = None  # moving instead of answering declines the offer
            if g.ply <= 40:
                opening = identify(g.moves)
                if opening:
                    g.opening = {"eco": opening.eco, "name": opening.name}
            outcome = automatic_outcome(board)
            if outcome:
                self._end(g, outcome, now)

        game, version, _, _ = await store.mutate(game_id, change)
        MOVES.inc()
        await self._after_change(game, version)
        MOVE_LATENCY.observe(time.perf_counter() - started)

    async def resign(self, user_id: str, game_id: str) -> None:
        def change(g: LiveGame) -> None:
            color = self._require_active_player(g, user_id)
            if g.ply < 2:
                self._end(g, Outcome("*", "aborted"), now_ms())
            else:
                self._end(g, Outcome("0-1" if color == "white" else "1-0", "resignation"), now_ms())

        await self._run(game_id, change)

    async def abort(self, user_id: str, game_id: str) -> None:
        def change(g: LiveGame) -> None:
            self._require_active_player(g, user_id)
            if g.ply >= 2:
                raise IllegalAction("Too late to abort; you can resign instead.")
            self._end(g, Outcome("*", "aborted"), now_ms())

        await self._run(game_id, change)

    async def offer_draw(self, user_id: str, game_id: str) -> None:
        def change(g: LiveGame) -> None:
            color = self._require_active_player(g, user_id)
            if g.ply < 2:
                raise IllegalAction("Make a move first.")
            if g.draw_offer == other(color):  # both want a draw: it's a draw
                self._end(g, Outcome("1/2-1/2", "agreement"), now_ms())
            elif g.draw_offer == color:
                raise NoChange
            else:
                g.draw_offer = color

        await self._run(game_id, change)

    async def answer_draw(self, user_id: str, game_id: str, accept: bool) -> None:
        def change(g: LiveGame) -> None:
            color = self._require_active_player(g, user_id)
            if g.draw_offer != other(color):
                raise IllegalAction("There's no draw offer to answer.")
            if accept:
                self._end(g, Outcome("1/2-1/2", "agreement"), now_ms())
            else:
                g.draw_offer = None

        await self._run(game_id, change)

    async def claim_win(self, user_id: str, game_id: str) -> None:
        def change(g: LiveGame) -> None:
            color = self._require_active_player(g, user_id)
            gone_since = g.disconnected.get(other(color))
            now = now_ms()
            if gone_since is None or now - gone_since < CLAIM_AFTER_MS:
                raise IllegalAction("Your opponent is still connected (or only just left).")
            if g.ply < 2:
                self._end(g, Outcome("*", "aborted"), now)
            else:
                self._end(g, Outcome("1-0" if color == "white" else "0-1", "abandonment"), now)

        await self._run(game_id, change)

    async def set_presence(self, game_id: str, color: Color, online: bool) -> None:
        def change(g: LiveGame) -> None:
            if g.status != "active":
                raise NoChange
            current = g.disconnected.get(color)
            if online and current is not None:
                g.disconnected[color] = None
            elif not online and current is None:
                g.disconnected[color] = now_ms()
            else:
                raise NoChange

        await self._run(game_id, change)

    async def offer_rematch(self, user_id: str, game_id: str) -> None:
        new_id = new_game_id()

        def change(g: LiveGame) -> bool:
            color = g.color_of(user_id)
            if color is None:
                raise Forbidden("Only the players can ask for a rematch.")
            if g.status != "ended":
                raise IllegalAction("The game isn't over yet.")
            if g.rematch_game:
                raise IllegalAction("A rematch has already started.")
            if g.rematch_offer == other(color):
                g.rematch_game, g.rematch_offer = new_id, None
                return True
            if g.rematch_offer == color:
                raise NoChange
            g.rematch_offer = color
            return False

        # Both players must be free before we accept (checked outside `change`, which must stay pure).
        loaded = await store.load(game_id)
        if loaded and loaded[0].rematch_offer and loaded[0].rematch_offer != loaded[0].color_of(user_id):
            await self.ensure_free(loaded[0].white.id)
            await self.ensure_free(loaded[0].black.id)

        game, version, accepted, saved = await store.mutate(game_id, change)
        if saved:
            await self._broadcast(game, version)
        if accepted:
            # Colours swap; same time control and rated-ness.
            tc = TimeControl(key=game.tc_key, initial_ms=game.initial_ms, increment_ms=game.increment_ms)
            await self.create_game(
                game.black.id, game.white.id, tc, rated=game.rated, source="rematch", game_id=new_id
            )

    async def decline_rematch(self, user_id: str, game_id: str) -> None:
        def change(g: LiveGame) -> None:
            color = g.color_of(user_id)
            if color is None or g.rematch_offer != other(color):
                raise NoChange
            g.rematch_offer = None

        game, version, _, saved = await store.mutate(game_id, change)
        if saved:
            await self._broadcast(game, version)

    # ----------------------------------------------------------- timers & recovery
    async def on_deadline(self, game_id: str) -> None:
        """Called by the timer scheduler. Ends the game if a deadline really passed."""
        loaded = await store.load(game_id)
        if loaded is None:
            await self._timers.set(game_id, None)
            return
        if loaded[0].status == "ended":
            if loaded[0].archived:
                await self._timers.set(game_id, None)
            else:
                await self._after_change(*loaded)  # retry archiving
            return

        def change(g: LiveGame) -> None:
            if g.status != "active":
                raise NoChange
            now = now_ms()
            abort_at = first_move_deadline_ms(g.clock, g.ply)
            if abort_at is not None:
                if now < abort_at:
                    raise NoChange
                self._end(g, Outcome("*", "aborted"), now)
                return
            flag_at = flag_deadline_ms(g.clock, g.white_to_move, g.ply)
            if flag_at is None or now < flag_at:
                raise NoChange
            self._end(g, timeout_outcome(board_from_moves(g.moves), flagged_white=g.white_to_move), now)

        game, version, _, saved = await store.mutate(game_id, change)
        if saved:
            await self._after_change(game, version)
        else:
            self._timers.arm_local(game_id, game.next_deadline_ms())  # fired early; try again later

    async def recover(self) -> None:
        """At startup: finish archiving games that ended while the server was down."""
        for game_id in await store.live_ids(1000):
            loaded = await store.load(game_id)
            if loaded is None:
                await redis().srem(store.LIVE_SET, game_id)
            elif loaded[0].status == "ended":
                await self._after_change(*loaded)

    # --------------------------------------------------------------- internals
    async def _run(self, game_id: str, change: Callable[[LiveGame], None]) -> None:
        game, version, _, saved = await store.mutate(game_id, change)
        if saved:
            await self._after_change(game, version)

    def _require_active_player(self, g: LiveGame, user_id: str) -> Color:
        color = g.color_of(user_id)
        if color is None:
            raise Forbidden("You're not playing in this game.")
        if g.status != "active":
            raise IllegalAction("The game is over.", code="game_over")
        return color

    def _require_turn_player(self, g: LiveGame, user_id: str) -> Color:
        color = self._require_active_player(g, user_id)
        if g.turn != color:
            raise IllegalAction("It's not your turn.", code="not_your_turn")
        return color

    @staticmethod
    def _end(g: LiveGame, outcome: Outcome, now: int, *, freeze: bool = True) -> None:
        if freeze:
            white_ms, black_ms = remaining_ms(g.clock, g.white_to_move, g.ply, now)
            g.clock = ClockState(white_ms=white_ms, black_ms=black_ms, turn_started_ms=now)
        g.status = "ended"
        g.result = outcome.result
        g.termination = outcome.termination
        g.ended_ms = now
        g.draw_offer = None

    async def _after_change(self, game: LiveGame, version: int) -> None:
        if game.status == "ended" and not game.archived:
            version = await self._finalize(game, version)
        elif game.status == "active":
            await self._timers.set(game.id, game.next_deadline_ms())
        await self._broadcast(game, version)

    async def _finalize(self, game: LiveGame, version: int) -> int:
        """Archive to Postgres, record rating changes, free the players."""
        await self._timers.set(game.id, None)
        try:
            deltas = await archive_game(game)
        except Exception:
            # Postgres unreachable: the game stays 'ended, not archived' in Redis and
            # recover() / the next deadline sweep retries. Players still see the result.
            log.exception("archive_failed", game_id=game.id)
            await self._timers.set(game.id, now_ms() + 30_000)  # retry via the deadline path
            return version

        def mark(g: LiveGame) -> None:
            if g.archived:
                raise NoChange
            g.archived = True
            g.rating_deltas = deltas

        updated, version, _, _ = await store.mutate(game.id, mark)
        game.archived, game.rating_deltas = updated.archived, updated.rating_deltas
        game.rematch_offer, game.rematch_game = updated.rematch_offer, updated.rematch_game
        await store.finish_bookkeeping(game)
        GAMES_FINISHED.labels(game.termination or "unknown").inc()
        log.info("game_finished", game_id=game.id, result=game.result, termination=game.termination)
        return version

    async def _broadcast(self, game: LiveGame, version: int) -> None:
        await self._publish(
            game_channel(game.id), {"type": "game.state", "game": game.snapshot(now_ms(), version)}
        )
