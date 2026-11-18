"""Sign up, sign in, token refresh, sign out, and Google sign-in."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import google
from ..auth.deps import CurrentUser, client_ip, same_origin
from ..auth.passwords import hash_password, needs_rehash, verify_password
from ..auth.tokens import (
    REFRESH_COOKIE,
    create_access_token,
    issue_refresh_token,
    revoke_token,
    rotate_refresh_token,
)
from ..auth.users import by_id, by_username, create_user, ratings_for, validate_password
from ..config import Settings, get_settings
from ..db import get_session
from ..db.models import User
from ..errors import AppError, NotFound, Unauthorized
from ..logging import log
from ..security import ratelimit

router = APIRouter(prefix="/api/auth", tags=["auth"])
DB = Annotated[AsyncSession, Depends(get_session)]
Cfg = Annotated[Settings, Depends(get_settings)]


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=256)


class UsernameOnly(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=40)


def _set_refresh_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,  # JavaScript can't read it, so XSS can't steal it
        secure=settings.secure_cookies,
        samesite="strict",  # never sent on requests started by other sites
        path="/api/auth",  # only sent to the auth endpoints, not every API call
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE, path="/api/auth", secure=settings.secure_cookies, samesite="strict"
    )


async def _session_payload(db: AsyncSession, settings: Settings, user: User) -> dict[str, object]:
    return {
        "access_token": create_access_token(settings, user.id, user.username),
        "expires_in": settings.access_token_ttl_seconds,
        "user": {
            "id": str(user.id),
            "username": user.username,
            "chesscom_username": user.chesscom_username,
            "has_password": user.password_hash is not None,
            "ratings": await ratings_for(db, user.id),
        },
    }


@router.get("/config")
async def auth_config(settings: Cfg) -> dict[str, bool]:
    return {"google": settings.google_enabled}


@router.post("/register")
async def register(
    body: Credentials, request: Request, response: Response, db: DB, settings: Cfg
) -> dict[str, object]:
    await ratelimit.hit(f"register:{client_ip(request)}", limit=5, window_s=3600)
    validate_password(body.password)
    user = await create_user(db, body.username, password_hash=await hash_password(body.password))
    token = await issue_refresh_token(db, settings, user.id, user_agent=request.headers.get("user-agent"))
    _set_refresh_cookie(response, settings, token)
    log.info("user_registered", user_id=str(user.id))
    return await _session_payload(db, settings, user)


@router.post("/login")
async def login(
    body: Credentials, request: Request, response: Response, db: DB, settings: Cfg
) -> dict[str, object]:
    # Two limits: per IP (one attacker, many accounts) and per account (many IPs, one victim).
    await ratelimit.hit(f"login:ip:{client_ip(request)}", limit=20, window_s=900)
    await ratelimit.hit(f"login:user:{body.username.lower()}", limit=10, window_s=900)
    user = await by_username(db, body.username)
    ok = await verify_password(user.password_hash if user else None, body.password)
    if not ok or user is None:
        raise Unauthorized("Wrong username or password.", code="bad_credentials")
    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = await hash_password(body.password)
    token = await issue_refresh_token(db, settings, user.id, user_agent=request.headers.get("user-agent"))
    _set_refresh_cookie(response, settings, token)
    return await _session_payload(db, settings, user)


@router.post("/refresh", dependencies=[Depends(same_origin)])
async def refresh(request: Request, response: Response, db: DB, settings: Cfg) -> dict[str, object]:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise Unauthorized("Not signed in.", code="no_session")
    user_id, new_token = await rotate_refresh_token(db, settings, token, request.headers.get("user-agent"))
    user = await by_id(db, user_id)
    if user is None:
        raise Unauthorized("Account not found.", code="no_session")
    _set_refresh_cookie(response, settings, new_token)
    return await _session_payload(db, settings, user)


@router.post("/logout", dependencies=[Depends(same_origin)])
async def logout(request: Request, response: Response, db: DB, settings: Cfg) -> dict[str, bool]:
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        await revoke_token(db, settings, token)
    _clear_refresh_cookie(response, settings)
    return {"ok": True}


@router.get("/me")
async def me(claims: CurrentUser, db: DB, settings: Cfg) -> dict[str, object]:
    user = await by_id(db, claims.user_id)
    if user is None:
        raise NotFound("Account not found.")
    payload = await _session_payload(db, settings, user)
    return payload["user"]  # type: ignore[return-value]


# ------------------------------------------------------------------ Google
@router.get("/google/start")
async def google_start(settings: Cfg) -> RedirectResponse:
    if not settings.google_enabled:
        raise NotFound("Google sign-in isn't enabled.")
    url, cookie = google.start_flow(settings)
    resp = RedirectResponse(url, status_code=302)
    # Lax (not Strict): this cookie must come back on Google's cross-site redirect to our callback.
    resp.set_cookie(
        google.FLOW_COOKIE,
        cookie,
        max_age=int(google.FLOW_TTL.total_seconds()),
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/api/auth/google",
    )
    return resp


@router.get("/google/callback")
async def google_callback(request: Request, db: DB, settings: Cfg) -> RedirectResponse:
    if not settings.google_enabled:
        raise NotFound("Google sign-in isn't enabled.")
    await ratelimit.hit(f"google:{client_ip(request)}", limit=20, window_s=900)
    code, state = request.query_params.get("code"), request.query_params.get("state")
    if not code or not state:
        return RedirectResponse("/login?error=google_cancelled", status_code=302)
    try:
        sub = await google.finish_flow(
            settings, code=code, state=state, flow_cookie=request.cookies.get(google.FLOW_COOKIE)
        )
    except AppError:
        return RedirectResponse("/login?error=google_failed", status_code=302)

    user = (await db.execute(select(User).where(User.google_sub == sub))).scalar_one_or_none()
    if user is None:
        # First visit: pick a username on /welcome. The Google id waits in a signed cookie.
        resp = RedirectResponse("/welcome", status_code=302)
        resp.set_cookie(
            google.PENDING_COOKIE,
            google.pending_cookie(settings, sub),
            max_age=int(google.PENDING_TTL.total_seconds()),
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            path="/api/auth/google",
        )
    else:
        resp = RedirectResponse("/", status_code=302)
        token = await issue_refresh_token(db, settings, user.id, user_agent=request.headers.get("user-agent"))
        _set_refresh_cookie(resp, settings, token)
    resp.delete_cookie(google.FLOW_COOKIE, path="/api/auth/google")
    return resp


@router.post("/google/complete", dependencies=[Depends(same_origin)])
async def google_complete(
    body: UsernameOnly, request: Request, response: Response, db: DB, settings: Cfg
) -> dict[str, object]:
    sub = google.read_pending(settings, request.cookies.get(google.PENDING_COOKIE))
    existing = (await db.execute(select(User).where(User.google_sub == sub))).scalar_one_or_none()
    user = existing or await create_user(db, body.username, google_sub=sub)
    token = await issue_refresh_token(db, settings, user.id, user_agent=request.headers.get("user-agent"))
    _set_refresh_cookie(response, settings, token)
    response.delete_cookie(google.PENDING_COOKIE, path="/api/auth/google")
    return await _session_payload(db, settings, user)
