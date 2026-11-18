"""FastAPI dependencies: who is calling, and from where."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..config import Settings, get_settings
from ..errors import Forbidden, Unauthorized
from .tokens import AccessClaims, decode_access_token


def client_ip(request: Request) -> str:
    """Real client IP. Only trusts X-Forwarded-For behind a known proxy (TRUST_PROXY)."""
    settings = get_settings()
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def optional_user(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> AccessClaims | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return decode_access_token(settings, header[7:].strip())


def current_user(claims: Annotated[AccessClaims | None, Depends(optional_user)]) -> AccessClaims:
    if claims is None:
        raise Unauthorized("Please sign in.")
    return claims


def same_origin(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    """CSRF guard for endpoints authenticated by cookie (refresh, logout).

    Browsers always send Origin on cross-site POSTs; if it isn't our site, refuse.
    The SameSite=Strict cookie is the first line of defence; this is the second.
    """
    origin = request.headers.get("origin")
    if origin is None or origin.rstrip("/") != settings.app_origin:
        raise Forbidden("Cross-site request blocked.", code="bad_origin")


CurrentUser = Annotated[AccessClaims, Depends(current_user)]
OptionalUser = Annotated[AccessClaims | None, Depends(optional_user)]
