"""Security headers and request ids for every HTTP response (pure ASGI middleware).

Written as raw ASGI instead of FastAPI's @app.middleware("http") because that
helper wraps responses in a way that breaks streaming and WebSockets.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog

from ..config import Settings
from ..metrics import HTTP_LATENCY

log = structlog.get_logger("shahmaat.http")


def content_security_policy(settings: Settings) -> str:
    ws_origin = settings.app_origin.replace("https://", "wss://").replace("http://", "ws://")
    return "; ".join(
        [
            "default-src 'self'",
            # Stockfish is WebAssembly; browsers need this to compile it. No 'unsafe-eval' for JS.
            "script-src 'self' 'wasm-unsafe-eval'",
            "worker-src 'self' blob:",
            # The board library positions pieces with inline style attributes.
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "font-src 'self' data:",
            f"connect-src 'self' {ws_origin}",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self' https://accounts.google.com",
            "object-src 'none'",
        ]
    )


class SecurityHeadersMiddleware:
    def __init__(self, app: Any, settings: Settings) -> None:
        self.app = app
        headers = [
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
            (b"cross-origin-opener-policy", b"same-origin"),
            (b"content-security-policy", content_security_policy(settings).encode()),
        ]
        if settings.secure_cookies:
            headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
        self.headers = headers

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex[:12]
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                existing = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in self.headers if k not in existing]
                message["headers"] = [
                    *message.get("headers", []),
                    *extra,
                    (b"x-request-id", request_id.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            route = scope.get("route")
            path_label = getattr(route, "path", None) or (
                "static" if not scope["path"].startswith("/api") else "unmatched"
            )
            HTTP_LATENCY.labels(scope["method"], path_label, str(status_holder["status"])).observe(elapsed)
            if scope["path"].startswith("/api") and scope["path"] != "/api/health":
                log.info(
                    "http",
                    method=scope["method"],
                    path=scope["path"],
                    status=status_holder["status"],
                    ms=round(elapsed * 1000, 1),
                )
            structlog.contextvars.clear_contextvars()
