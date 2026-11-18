"""'Continue with Google' — OpenID Connect authorization-code flow with PKCE.

The three random values and what each one stops:
* state:          a forged callback (someone tricking your browser into logging
                  into THEIR account). Must match the value in our cookie.
* nonce:          a replayed ID token. Google copies it into the signed token.
* code_verifier:  PKCE. A stolen authorization code is useless without it.

We ask only for the `openid` scope: Google tells us a stable account id (`sub`)
and nothing else — no email, no name. Less data held, less to leak.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from ..config import Settings
from ..errors import Unauthorized, UpstreamError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")

FLOW_COOKIE = "sm_oauth"
PENDING_COOKIE = "sm_google_pending"
FLOW_TTL = timedelta(minutes=10)
PENDING_TTL = timedelta(minutes=15)

_jwks_client: jwt.PyJWKClient | None = None


def redirect_uri(settings: Settings) -> str:
    return f"{settings.app_origin}/api/auth/google/callback"


def _sign(settings: Settings, payload: dict[str, Any], ttl: timedelta, purpose: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode({**payload, "aud": purpose, "iat": now, "exp": now + ttl}, settings.jwt_secret, "HS256")


def _unsign(settings: Settings, token: str | None, purpose: str) -> dict[str, Any]:
    if not token:
        raise Unauthorized("Sign-in expired. Please try again.", code="oauth_expired")
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], audience=purpose)
    except jwt.PyJWTError as exc:
        raise Unauthorized("Sign-in expired. Please try again.", code="oauth_expired") from exc


def start_flow(settings: Settings) -> tuple[str, str]:
    """Returns (Google URL to redirect to, signed cookie holding our secrets for the callback)."""
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(settings),
        "response_type": "code",
        "scope": "openid",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    cookie = _sign(settings, {"state": state, "nonce": nonce, "verifier": verifier}, FLOW_TTL, "oauth-flow")
    return f"{AUTH_URL}?{urlencode(params)}", cookie


async def finish_flow(settings: Settings, *, code: str, state: str, flow_cookie: str | None) -> str:
    """Verifies the callback and returns Google's account id (`sub`)."""
    flow = _unsign(settings, flow_cookie, "oauth-flow")
    if not secrets.compare_digest(flow["state"], state):
        raise Unauthorized("Sign-in failed (state mismatch).", code="oauth_state")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri(settings),
                "grant_type": "authorization_code",
                "code_verifier": flow["verifier"],
            },
        )
    if resp.status_code != 200:
        raise UpstreamError("Google sign-in failed. Please try again.")
    id_token = resp.json().get("id_token")
    if not id_token:
        raise UpstreamError("Google sign-in failed. Please try again.")

    claims = await asyncio.to_thread(_verify_id_token, settings, id_token)
    if not secrets.compare_digest(str(claims.get("nonce", "")), flow["nonce"]):
        raise Unauthorized("Sign-in failed (nonce mismatch).", code="oauth_nonce")
    return str(claims["sub"])


def _verify_id_token(settings: Settings, id_token: str) -> dict[str, Any]:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600)
    try:
        key = _jwks_client.get_signing_key_from_jwt(id_token)
        claims: dict[str, Any] = jwt.decode(
            id_token,
            key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=ISSUERS,  # type: ignore[arg-type]
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise Unauthorized("Google sign-in couldn't be verified.", code="oauth_token") from exc
    return claims


def pending_cookie(settings: Settings, google_sub: str) -> str:
    return _sign(settings, {"sub": google_sub}, PENDING_TTL, "google-pending")


def read_pending(settings: Settings, cookie: str | None) -> str:
    return str(_unsign(settings, cookie, "google-pending")["sub"])
