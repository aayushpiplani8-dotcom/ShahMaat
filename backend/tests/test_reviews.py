"""Reviews over HTTP: fair-play guard, storage, deeper-wins, puzzles from mistakes."""

from __future__ import annotations

from conftest import register
from test_live_games import play, start_game


def lines_for(n_positions: int, blunder_at: int | None = None) -> list[dict]:
    out = []
    for i in range(n_positions):
        cp = 20
        if blunder_at is not None and i > blunder_at:
            cp = 900  # after the blunder White is winning
        out.append({"cp": cp, "best": None, "pv": []})
    return out


def test_review_flow_creates_puzzles_for_the_player(client) -> None:
    white, black, game_id = start_game(client)
    bh = {"authorization": f"Bearer {black.session['access_token']}"}

    # No engine help while the game is on.
    early = client.post(f"/api/reviews/live/{game_id}", json={"depth": 12, "lines": lines_for(1)}, headers=bh)
    assert early.status_code == 403 and early.json()["error"]["code"] == "game_in_progress"

    moves = ["e2e4", "e7e5", "g1f3", "f7f6", "f3e5", "f6e5"]
    play(white, black, game_id, moves)
    black.send({"type": "game.action", "game_id": game_id, "action": "resign"})
    black.state(lambda g: g["status"] == "ended")

    lines = lines_for(len(moves) + 1, blunder_at=3)
    lines[3] = {"cp": 20, "best": "b8c6", "pv": ["b8c6", "f1b5"]}  # engine wanted Nc6, Black played f6?
    resp = client.post(f"/api/reviews/live/{game_id}", json={"depth": 14, "lines": lines}, headers=bh)
    assert resp.status_code == 200, resp.text
    review = resp.json()
    assert review["moves"][3]["san"] == "f6" and review["moves"][3]["class"] == "blunder"
    assert review["puzzles_created"] == 1
    assert review["phases"]["black"]["opening"] is not None

    # The opponent can build their own puzzles from the stored review without re-running the engine.
    wh = {"authorization": f"Bearer {white.session['access_token']}"}
    assert client.post(f"/api/reviews/live/{game_id}/puzzles", headers=wh).json()["puzzles_created"] == 0
    assert (
        client.post(f"/api/reviews/live/{game_id}/puzzles", headers=bh).json()["puzzles_created"] == 0
    )  # no dupes

    # Anyone can read a stored review of a finished game.
    assert client.get(f"/api/reviews/live/{game_id}").json()["depth"] == 14

    # A shallower review doesn't overwrite a deeper one.
    client.post(f"/api/reviews/live/{game_id}", json={"depth": 8, "lines": lines}, headers=bh)
    assert client.get(f"/api/reviews/live/{game_id}").json()["depth"] == 14

    # The puzzle is served without its answer, and checked on the server.
    puzzle = client.get("/api/puzzles/next", headers=bh).json()["puzzle"]
    assert puzzle and "solution" not in puzzle and puzzle["played"] == "f7f6"
    wrong = client.post(f"/api/puzzles/{puzzle['id']}/attempt", json={"move": "a7a6"}, headers=bh).json()
    assert wrong["correct"] is False and wrong["box"] == 0
    right = client.post(f"/api/puzzles/{puzzle['id']}/attempt", json={"move": "b8c6"}, headers=bh).json()
    assert right["correct"] is True and right["box"] == 1
    stats = client.get("/api/puzzles/stats", headers=bh).json()
    assert stats["total"] == 1 and stats["due"] == 0

    # Another user's puzzles are invisible.
    other = register(client, "stranger")
    oh = {"authorization": f"Bearer {other['access_token']}"}
    assert (
        client.post(f"/api/puzzles/{puzzle['id']}/attempt", json={"move": "b8c6"}, headers=oh).status_code
        == 404
    )
    for p in (white, black):
        p.close()


def test_score_only_endpoint_validates_input(client) -> None:
    ok = client.post(
        "/api/reviews/score",
        json={"depth": 10, "moves": ["e2e4"], "lines": [{"cp": 20}, {"cp": 25}]},
    )
    assert ok.status_code == 200 and ok.json()["moves"][0]["san"] == "e4"
    bad_len = client.post("/api/reviews/score", json={"depth": 10, "moves": ["e2e4"], "lines": [{"cp": 20}]})
    assert bad_len.status_code == 400
    bad_move = client.post(
        "/api/reviews/score",
        json={"depth": 10, "moves": ["e2e4"], "lines": [{"cp": 0, "best": "zz"}, {"cp": 0}]},
    )
    assert bad_move.status_code == 422
