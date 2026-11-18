"""WebSocket messages from the browser, validated with Pydantic.

Every message must match exactly one of these shapes. Unknown types, extra
fields, oversized values and malformed moves are rejected before any game code
runs. The user id is NEVER taken from a message; it comes from the token the
connection was authenticated with.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

GameId = Annotated[str, Field(pattern=r"^[A-Za-z0-9]{10}$")]
Ref = Annotated[int | None, Field(default=None, ge=0, le=2**31)]

MAX_MESSAGE_BYTES = 4096


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ref: Ref = None  # echoed back in errors so the client knows which request failed


class Auth(_Msg):
    type: Literal["auth"]
    token: Annotated[str | None, Field(max_length=2048)] = None  # None = watch-only guest


class Pong(_Msg):
    type: Literal["pong"]
    t: int


class QueueJoin(_Msg):
    type: Literal["queue.join"]
    tc: Annotated[str, Field(max_length=8)]


class QueueLeave(_Msg):
    type: Literal["queue.leave"]


class Watch(_Msg):
    type: Literal["game.watch"]
    game_id: GameId


class Unwatch(_Msg):
    type: Literal["game.unwatch"]
    game_id: GameId


class Move(_Msg):
    type: Literal["game.move"]
    game_id: GameId
    uci: Annotated[str, Field(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")]
    ply: Annotated[int, Field(ge=0, le=2000)]  # the position the move was made in (stale-move guard)


class Action(_Msg):
    type: Literal["game.action"]
    game_id: GameId
    action: Literal[
        "resign",
        "abort",
        "offer_draw",
        "accept_draw",
        "decline_draw",
        "claim_win",
        "rematch",
        "decline_rematch",
    ]


ClientMessage = Annotated[
    Auth | Pong | QueueJoin | QueueLeave | Watch | Unwatch | Move | Action,
    Field(discriminator="type"),
]
client_message = TypeAdapter(ClientMessage)
