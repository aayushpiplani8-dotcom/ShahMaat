"""Accounts and sessions over real HTTP."""

from __future__ import annotations

from conftest import ORIGIN, register

from shahmaat.auth.tokens import REFRESH_COOKIE


def test_register_login_and_me(client) -> None:
    session = register(client, "Magnus")
    assert session["user"]["username"] == "Magnus"
    assert set(session["user"]["ratings"]) == {"bullet", "blitz", "rapid"}
    assert session["user"]["ratings"]["blitz"]["rating"] == 1500

    # Usernames are unique regardless of case.
    resp = client.post("/api/auth/register", json={"username": "magnus", "password": "password123"})
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "username_taken"

    resp = client.post("/api/auth/login", json={"username": "MAGNUS", "password": "password123"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    me = client.get("/api/auth/me", headers={"authorization": f"Bearer {token}"})
    assert me.json()["username"] == "Magnus"


def test_wrong_password_and_unknown_user_look_identical(client) -> None:
    register(client, "alice")
    a = client.post("/api/auth/login", json={"username": "alice", "password": "wrong-password"})
    b = client.post("/api/auth/login", json={"username": "nobody", "password": "wrong-password"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_validation(client) -> None:
    assert (
        client.post("/api/auth/register", json={"username": "ab", "password": "password123"}).status_code
        == 400
    )
    assert (
        client.post(
            "/api/auth/register", json={"username": "<script>", "password": "password123"}
        ).status_code
        == 400
    )
    assert (
        client.post("/api/auth/register", json={"username": "admin", "password": "password123"}).status_code
        == 400
    )
    assert (
        client.post("/api/auth/register", json={"username": "okname", "password": "short"}).status_code == 400
    )
    extra = client.post(
        "/api/auth/register", json={"username": "okname", "password": "password123", "is_admin": True}
    )
    assert extra.status_code == 422  # unknown fields are rejected, not ignored


def test_refresh_rotates_and_replay_kills_the_session(client) -> None:
    register(client, "bob")
    first = client.cookies.get(REFRESH_COOKIE)
    assert first

    r1 = client.post("/api/auth/refresh", headers=ORIGIN)
    assert r1.status_code == 200
    second = client.cookies.get(REFRESH_COOKIE)
    assert second and second != first

    # An attacker replays the old token later (past the race grace period).
    from datetime import timedelta

    import shahmaat.auth.tokens as tokens

    original = tokens.REUSE_GRACE
    tokens.REUSE_GRACE = timedelta(seconds=-1)
    try:
        client.cookies.set(REFRESH_COOKIE, first, path="/api/auth")
        replay = client.post("/api/auth/refresh", headers=ORIGIN)
        assert replay.status_code == 401 and replay.json()["error"]["code"] == "session_reused"
        # ...and now even the legitimate newer token is dead: the whole login was revoked.
        client.cookies.set(REFRESH_COOKIE, second, path="/api/auth")
        assert client.post("/api/auth/refresh", headers=ORIGIN).status_code == 401
    finally:
        tokens.REUSE_GRACE = original


def test_cookie_endpoints_refuse_cross_site_requests(client) -> None:
    register(client, "carol")
    evil = client.post("/api/auth/refresh", headers={"origin": "https://evil.example"})
    assert evil.status_code == 403
    missing = client.post("/api/auth/refresh")
    assert missing.status_code == 403


def test_logout_revokes(client) -> None:
    register(client, "dave")
    assert client.post("/api/auth/logout", headers=ORIGIN).status_code == 200
    assert client.post("/api/auth/refresh", headers=ORIGIN).status_code == 401


def test_login_is_rate_limited(client) -> None:
    register(client, "erin")
    codes = [
        client.post("/api/auth/login", json={"username": "erin", "password": "nope-nope"}).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_tampered_token_is_rejected(client) -> None:
    token = register(client, "frank")["access_token"]
    header, payload, sig = token.split(".")
    forged = f"{header}.{payload}.{sig[::-1]}"
    assert client.get("/api/auth/me", headers={"authorization": f"Bearer {forged}"}).status_code == 401


def test_security_headers_present(client) -> None:
    resp = client.get("/api/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["x-request-id"]
