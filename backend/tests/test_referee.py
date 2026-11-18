"""The hard cases: simultaneous requests, clocks running out, and server restarts."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from conftest import make_user
from sqlalchemy import select

from shahmaat.chess_core.timecontrols import TIME_CONTROLS
from shahmaat.db import session_scope
from shahmaat.db.models import Game, Rating
from shahmaat.errors import AppError
from shahmaat.game import store
from shahmaat.game.store import NoChange


async def new_game(rt, tc: str = "3+2"):
    w = await make_user(f"w{uuid.uuid4().hex[:6]}")
    b = await make_user(f"b{uuid.uuid4().hex[:6]}")
    game = await rt.games.create_game(w, b, TIME_CONTROLS[tc], rated=True, source="queue")
    return game.id, w, b


async def test_simultaneous_resignations_produce_one_result(rt) -> None:
    game_id, w, b = await new_game(rt)
    await rt.games.move(w, game_id, "e2e4", 0)
    await rt.games.move(b, game_id, "e7e5", 1)

    results = await asyncio.gather(
        rt.games.resign(w, game_id), rt.games.resign(b, game_id), return_exceptions=True
    )
    assert sum(isinstance(r, AppError) for r in results) == 1  # exactly one resignation counted

    game, _ = await store.load(game_id)
    assert game.termination == "resignation"
    async with session_scope() as s:
        games = (await s.execute(select(Rating.games).where(Rating.time_class == "blitz"))).scalars().all()
    assert sorted(games) == [1, 1]  # ratings changed once, not twice


async def test_parallel_moves_only_one_applies(rt) -> None:
    game_id, w, _ = await new_game(rt)
    results = await asyncio.gather(
        rt.games.move(w, game_id, "e2e4", 0),
        rt.games.move(w, game_id, "d2d4", 0),
        return_exceptions=True,
    )
    assert sum(r is None for r in results) == 1
    game, _ = await store.load(game_id)
    assert len(game.moves) == 1


async def test_flag_falls_on_the_server_timer(rt) -> None:
    game_id, w, b = await new_game(rt, "1+0")
    for i, uci in enumerate(["e2e4", "e7e5", "g1f3"]):
        await rt.games.move(w if i % 2 == 0 else b, game_id, uci, i)

    # Pretend Black has been thinking for two minutes.
    def rewind(g):
        g.clock.turn_started_ms -= 120_000

    await store.mutate(game_id, rewind)
    await rt.games.on_deadline(game_id)
    game, _ = await store.load(game_id)
    assert game.status == "ended" and game.termination == "timeout" and game.result == "1-0"
    assert game.clock.black_ms == 0
    async with session_scope() as s:
        assert (await s.get(Game, game_id)) is not None


async def test_timer_firing_early_changes_nothing(rt) -> None:
    game_id, w, b = await new_game(rt)
    await rt.games.move(w, game_id, "e2e4", 0)
    await rt.games.move(b, game_id, "e7e5", 1)
    _, version_before = await store.load(game_id)
    await rt.games.on_deadline(game_id)
    game, version_after = await store.load(game_id)
    assert game.status == "active" and version_after == version_before


async def test_no_first_move_aborts_the_game(rt) -> None:
    game_id, _, _ = await new_game(rt)

    def rewind(g):
        g.clock.turn_started_ms -= 31_000

    await store.mutate(game_id, rewind)
    await rt.games.on_deadline(game_id)
    game, _ = await store.load(game_id)
    assert game.termination == "aborted"


async def test_late_move_loses_on_time_even_if_legal(rt) -> None:
    game_id, w, b = await new_game(rt, "1+0")
    await rt.games.move(w, game_id, "e2e4", 0)
    await rt.games.move(b, game_id, "e7e5", 1)

    def rewind(g):
        g.clock.turn_started_ms -= 61_000

    await store.mutate(game_id, rewind)
    await rt.games.move(w, game_id, "g1f3", 2)  # arrives after the flag
    game, _ = await store.load(game_id)
    assert game.termination == "timeout" and game.result == "0-1" and game.moves == ["e2e4", "e7e5"]


async def test_disconnect_claim(rt) -> None:
    game_id, w, b = await new_game(rt)
    await rt.games.move(w, game_id, "e2e4", 0)
    await rt.games.move(b, game_id, "e7e5", 1)
    await rt.games.set_presence(game_id, "black", online=False)
    with pytest.raises(AppError):
        await rt.games.claim_win(w, game_id)  # too soon

    def long_ago(g):
        g.disconnected["black"] -= 31_000

    await store.mutate(game_id, long_ago)
    await rt.games.claim_win(w, game_id)
    game, _ = await store.load(game_id)
    assert game.result == "1-0" and game.termination == "abandonment"


async def test_game_survives_a_server_restart(rt, settings) -> None:
    from shahmaat.runtime import build_runtime

    game_id, w, b = await new_game(rt)
    await rt.games.move(w, game_id, "e2e4", 0)
    await rt.stop()  # server dies mid-game

    fresh = build_runtime(settings)
    await fresh.start()  # a new process comes up
    try:
        await fresh.games.move(b, game_id, "c7c5", 1)
        game, _ = await store.load(game_id)
        assert game.moves == ["e2e4", "c7c5"] and game.status == "active"
        assert await store.active_game_of(w) == game_id
    finally:
        await fresh.stop()
        await rt.start()  # so the fixture can stop it cleanly


async def test_archiving_is_idempotent(rt) -> None:
    from shahmaat.game.archive import archive_game

    game_id, w, b = await new_game(rt)
    await rt.games.move(w, game_id, "e2e4", 0)
    await rt.games.move(b, game_id, "e7e5", 1)
    await rt.games.resign(b, game_id)
    game, _ = await store.load(game_id)
    again = await archive_game(game)  # e.g. a retry after a crash
    assert again == game.rating_deltas
    async with session_scope() as s:
        counts = (await s.execute(select(Rating.games).where(Rating.time_class == "blitz"))).scalars().all()
    assert sorted(counts) == [1, 1]


async def test_cannot_queue_while_playing(rt) -> None:
    game_id, w, _ = await new_game(rt)
    with pytest.raises(AppError) as exc:
        await rt.matchmaker.join(w, "3+2")
    assert exc.value.code == "already_playing"


async def test_matchmaking_prefers_close_ratings(rt) -> None:
    a = await make_user("near1")
    b = await make_user("near2")
    c = await make_user("far")
    async with session_scope() as s:
        row = await s.get(Rating, (uuid.UUID(c), "blitz"))
        row.rating = 2400
    await rt.matchmaker.join(c, "3+2")
    await rt.matchmaker.join(a, "3+2")
    assert rt.matchmaker.is_waiting(c) and rt.matchmaker.is_waiting(a)  # 900 points apart: no pairing
    await rt.matchmaker.join(b, "3+2")
    assert not rt.matchmaker.is_waiting(a) and not rt.matchmaker.is_waiting(b)
    assert rt.matchmaker.is_waiting(c)


async def test_mutate_nochange_does_not_bump_version(rt) -> None:
    game_id, _, _ = await new_game(rt)
    _, before = await store.load(game_id)

    def nothing(_):
        raise NoChange

    _, version, _, saved = await store.mutate(game_id, nothing)
    assert not saved and version == before
