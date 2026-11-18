"""Live play end to end: two real WebSocket clients, matchmaking, moves, results, ratings."""

from __future__ import annotations

import json
from typing import Any

from conftest import register


class Player:
    def __init__(self, client, name: str) -> None:
        self.session = register(client, name)
        self.name = name
        self.ws = client.websocket_connect("/ws").__enter__()
        self.send({"type": "auth", "token": self.session["access_token"]})
        hello = self.until(lambda m: m["type"] == "hello")
        assert hello["user"]["username"] == name

    def send(self, msg: dict[str, Any]) -> None:
        self.ws.send_text(json.dumps(msg))

    def until(self, pred, limit: int = 50) -> dict[str, Any]:
        for _ in range(limit):
            msg = self.ws.receive_json()
            if pred(msg):
                return msg
        raise AssertionError("expected message never arrived")

    def state(self, pred=lambda g: True) -> dict[str, Any]:
        return self.until(lambda m: m["type"] == "game.state" and pred(m["game"]))["game"]

    def close(self) -> None:
        self.ws.__exit__(None, None, None)


def start_game(client) -> tuple[Player, Player, str]:
    a, b = Player(client, "anand"), Player(client, "carlsen")
    a.send({"type": "queue.join", "tc": "5+3"})
    assert a.until(lambda m: m["type"] == "queue.state")["status"] == "searching"
    b.send({"type": "queue.join", "tc": "5+3"})
    game_id = a.until(lambda m: m["type"] == "match.found")["game_id"]
    assert b.until(lambda m: m["type"] == "match.found")["game_id"] == game_id
    for p in (a, b):
        p.send({"type": "game.watch", "game_id": game_id})
    g = a.state()
    b.state()
    white, black = (a, b) if g["white"]["username"] == "anand" else (b, a)
    return white, black, game_id


def play(white: Player, black: Player, game_id: str, moves: list[str], start_ply: int = 0) -> dict[str, Any]:
    g: dict[str, Any] = {}
    for i, uci in enumerate(moves, start=start_ply):
        mover, other = (white, black) if i % 2 == 0 else (black, white)
        mover.send({"type": "game.move", "game_id": game_id, "uci": uci, "ply": i})
        g = mover.state(lambda s, n=i: s["ply"] == n + 1 or s["status"] == "ended")
        other.state(lambda s, n=i: s["ply"] == n + 1 or s["status"] == "ended")
    return g


def test_full_rated_game_updates_ratings_and_history(client) -> None:
    white, black, game_id = start_game(client)
    play(white, black, game_id, ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6"])
    white.send({"type": "game.move", "game_id": game_id, "uci": "h5f7", "ply": 6})
    final = white.state(lambda g: g["status"] == "ended" and g["rating_deltas"] is not None)
    assert final["result"] == "1-0" and final["termination"] == "checkmate"
    assert final["rating_deltas"]["white"] > 0 > final["rating_deltas"]["black"]
    assert final["opening"]["eco"].startswith("C")

    profile = client.get(f"/api/users/{white.name}").json()
    assert profile["ratings"]["blitz"]["games"] == 1 and profile["ratings"]["blitz"]["wins"] == 1
    history = client.get(f"/api/users/{black.name}/games").json()
    assert history["items"][0]["id"] == game_id
    pgn = client.get(f"/api/games/{game_id}/pgn").text
    assert "Qxf7#" in pgn and '[Result "1-0"]' in pgn
    for p in (white, black):
        p.close()


def test_server_rejects_cheating_attempts(client) -> None:
    white, black, game_id = start_game(client)
    # Moving out of turn
    black.send({"type": "game.move", "game_id": game_id, "uci": "e7e5", "ply": 0, "ref": 1})
    assert black.until(lambda m: m["type"] == "error")["code"] == "not_your_turn"
    # Illegal move
    white.send({"type": "game.move", "game_id": game_id, "uci": "e2e5", "ply": 0, "ref": 2})
    err = white.until(lambda m: m["type"] == "error")
    assert err["code"] == "illegal_action" and err["ref"] == 2
    # Smuggled extra field (e.g. trying to act as someone else)
    white.send({"type": "game.move", "game_id": game_id, "uci": "e2e4", "ply": 0, "user_id": "x"})
    assert white.until(lambda m: m["type"] == "error")["code"] == "bad_message"
    # Stale move (made for a position that no longer exists)
    play(white, black, game_id, ["e2e4"])
    white.send({"type": "game.move", "game_id": game_id, "uci": "d2d4", "ply": 0})
    assert white.until(lambda m: m["type"] == "error")["code"] in ("stale_move", "not_your_turn")
    for p in (white, black):
        p.close()


def test_draw_offer_and_resign_flow(client) -> None:
    white, black, game_id = start_game(client)
    play(white, black, game_id, ["d2d4", "d7d5"])
    white.send({"type": "game.action", "game_id": game_id, "action": "offer_draw"})
    assert black.state(lambda g: g["draw_offer"] == "white")
    black.send({"type": "game.action", "game_id": game_id, "action": "decline_draw"})
    assert white.state(lambda g: g["draw_offer"] is None and g["ply"] == 2)
    black.send({"type": "game.action", "game_id": game_id, "action": "resign"})
    final = white.state(lambda g: g["status"] == "ended")
    assert final["result"] == "1-0" and final["termination"] == "resignation"

    # Rematch: both ask, a new game starts with colours swapped.
    white.send({"type": "game.action", "game_id": game_id, "action": "rematch"})
    black.state(lambda g: g["rematch_offer"] == "white")
    black.send({"type": "game.action", "game_id": game_id, "action": "rematch"})
    new_id = white.until(lambda m: m["type"] == "match.found")["game_id"]
    assert new_id != game_id
    rematch = client.get(f"/api/games/{new_id}").json()["game"]
    assert rematch["white"]["username"] == black.name
    for p in (white, black):
        p.close()


def test_abort_before_first_moves_is_unrated(client) -> None:
    white, black, game_id = start_game(client)
    black.send({"type": "game.action", "game_id": game_id, "action": "abort"})
    final = white.state(lambda g: g["status"] == "ended")
    assert final["termination"] == "aborted" and final["result"] == "*"
    assert client.get(f"/api/users/{white.name}").json()["ratings"]["blitz"]["games"] == 0
    for p in (white, black):
        p.close()


def test_spectators_and_guests_can_watch_but_not_play(client) -> None:
    white, black, game_id = start_game(client)
    with client.websocket_connect("/ws") as guest:
        guest.send_text(json.dumps({"type": "auth", "token": None}))
        assert guest.receive_json()["user"] is None
        guest.send_text(json.dumps({"type": "game.watch", "game_id": game_id}))
        assert guest.receive_json()["type"] == "game.state"
        guest.send_text(json.dumps({"type": "game.move", "game_id": game_id, "uci": "e2e4", "ply": 0}))
        assert guest.receive_json()["code"] == "unauthorized"
        play(white, black, game_id, ["e2e4"])
        seen = guest.receive_json()
        assert seen["type"] == "game.state" and seen["game"]["moves"] == ["e2e4"]
    assert any(g["id"] == game_id for g in client.get("/api/games/live").json())
    for p in (white, black):
        p.close()


def test_socket_requires_auth_message_first(client) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "queue.join", "tc": "3+2"}))
        assert ws.receive_json()["type"] == "error"


def test_private_challenge_link(client) -> None:
    host = register(client, "hostess")
    guest = register(client, "visitor")
    h = {"authorization": f"Bearer {host['access_token']}"}
    g = {"authorization": f"Bearer {guest['access_token']}"}
    ch = client.post("/api/challenges", json={"tc": "10+5", "color": "white"}, headers=h).json()
    assert client.get(f"/api/challenges/{ch['code']}").json()["creator"] == "hostess"
    assert client.post(f"/api/challenges/{ch['code']}/accept", headers=h).status_code == 409  # not your own
    game_id = client.post(f"/api/challenges/{ch['code']}/accept", headers=g).json()["game_id"]
    game = client.get(f"/api/games/{game_id}").json()["game"]
    assert game["white"]["username"] == "hostess" and game["tc"]["key"] == "10+5" and not game["rated"]
    # Accepted links are single-use.
    assert client.post(f"/api/challenges/{ch['code']}/accept", headers=g).status_code == 404
