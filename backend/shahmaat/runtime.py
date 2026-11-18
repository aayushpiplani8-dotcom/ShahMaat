"""Wires the long-lived parts of the server together (one instance per process)."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .game.matchmaking import Matchmaker
from .game.service import GameService
from .game.timers import TimerScheduler
from .realtime.bus import Bus, LocalBus, RedisBus
from .realtime.hub import Hub
from .redis_client import redis


@dataclass(slots=True)
class Runtime:
    settings: Settings
    hub: Hub
    bus: Bus
    timers: TimerScheduler
    games: GameService
    matchmaker: Matchmaker

    async def start(self) -> None:
        await self.bus.start()
        await self.timers.start()
        await self.games.recover()
        await self.matchmaker.start()

    async def stop(self) -> None:
        await self.matchmaker.stop()
        await self.timers.stop()
        await self.bus.stop()


def build_runtime(settings: Settings) -> Runtime:
    hub = Hub()
    bus: Bus = RedisBus(redis(), hub.deliver) if settings.multi_instance else LocalBus(hub.deliver)
    hub.bus = bus

    games_ref: dict[str, GameService] = {}

    async def on_due(game_id: str) -> None:
        await games_ref["games"].on_deadline(game_id)

    timers = TimerScheduler(on_due)
    games = GameService(bus.publish, timers)
    games_ref["games"] = games
    hub.timers = timers

    if settings.multi_instance:

        async def share_deadline(game_id: str, deadline: int | None) -> None:
            await bus.publish("timers", {"game_id": game_id, "deadline": deadline})

        timers.publish_hook = share_deadline

    return Runtime(
        settings=settings,
        hub=hub,
        bus=bus,
        timers=timers,
        games=games,
        matchmaker=Matchmaker(games),
    )
