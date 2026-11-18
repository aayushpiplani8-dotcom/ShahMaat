"""Access tokens and rotating refresh tokens.

Two tokens, two jobs:
* Access token: a short-lived (15 min) signed JWT the browser keeps in memory and
  sends as `Authorization: Bearer ...`. Not stored anywhere on the server.
* Refresh token: a long random string in an httpOnly cookie that JavaScript can't
  read (so XSS can't steal it). It is used only to get a new access token.

Rotation with reuse detection: every refresh swaps the old token for a new one.
All tokens from one login share a `family_id`. If an already-used token shows up
again, someone copied it, so the whole family (that login) is revoked at once.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db.models import Session
from ..errors import Unauthorized

ALGORITHM = "HS256"
ISSUER = "shahmaat"
REFRESH_COOKIE = "sm_refresh"
REUSE_GRACE = timedelta(seconds=10)


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    username: str


def create_access_token(settings: Settings, user_id: uuid.UUID, username: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "name": username,
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_ttl_seconds),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],  # pinning the algorithm blocks "alg: none" style attacks
            issuer=ISSUER,
            options={"require": ["exp", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Session expired.", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid token.") from exc
    if payload.get("typ") != "access":
        raise Unauthorized("Invalid token.")
    return AccessClaims(user_id=uuid.UUID(payload["sub"]), username=str(payload.get("name", "")))


def _hash_refresh(settings: Settings, token: str) -> bytes:
    return hmac.new(settings.refresh_token_secret.encode(), token.encode(), hashlib.sha256).digest()


async def issue_refresh_token(
    db: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    *,
    family_id: uuid.UUID | None = None,
    user_agent: str | None = None,
) -> str:
    token = secrets.token_urlsafe(48)
    db.add(
        Session(
            user_id=user_id,
            family_id=family_id or uuid.uuid4(),
            token_hash=_hash_refresh(settings, token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
            user_agent=(user_agent or "")[:256] or None,
        )
    )
    await db.flush()
    return token


async def rotate_refresh_token(
    db: AsyncSession, settings: Settings, token: str, user_agent: str | None = None
) -> tuple[uuid.UUID, str]:
    """Exchanges a refresh token for a new one. Returns (user_id, new token)."""
    now = datetime.now(UTC)
    # FOR UPDATE: two tabs refreshing at the same moment are serialised, so exactly
    # one wins and the other is treated as reuse instead of both succeeding.
    row = (
        await db.execute(
            select(Session).where(Session.token_hash == _hash_refresh(settings, token)).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        raise Unauthorized("Please sign in again.", code="session_invalid")
    if row.used_at is not None:
        if now - row.used_at < REUSE_GRACE:
            # Two tabs refreshed at the same instant; the cookie jar already holds the
            # newer token, so the client just retries. Not an attack.
            raise Unauthorized("Refresh in progress, retry.", code="refresh_race")
        # Replay of a token that was exchanged a while ago: someone copied it.
        # Kill the whole login. Commit now, because raising rolls the session back.
        await revoke_family(db, row.family_id)
        await db.commit()
        raise Unauthorized("Please sign in again.", code="session_reused")
    row.used_at = now
    new_token = await issue_refresh_token(
        db, settings, row.user_id, family_id=row.family_id, user_agent=user_agent
    )
    return row.user_id, new_token


async def revoke_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    await db.execute(
        update(Session)
        .where(Session.family_id == family_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def revoke_token(db: AsyncSession, settings: Settings, token: str) -> None:
    row = (
        await db.execute(select(Session).where(Session.token_hash == _hash_refresh(settings, token)))
    ).scalar_one_or_none()
    if row is not None:
        await revoke_family(db, row.family_id)
