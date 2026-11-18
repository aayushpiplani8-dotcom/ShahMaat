"""Application factory: builds the FastAPI app and manages startup/shutdown.

Startup order matters: logging -> database -> Redis -> chess.com client ->
runtime (bus, timers, recovery of interrupted games, matchmaker).
Shutdown runs in reverse, so in-flight game timers stop before Redis closes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from . import db as database
from .api import auth, games, imports, puzzles, reviews, users
from .config import Settings, get_settings
from .errors import AppError, RateLimited
from .logging import log, setup_logging
from .realtime import endpoint as ws_endpoint
from .redis_client import close_redis, init_redis, redis
from .runtime import build_runtime
from .security.headers import SecurityHeadersMiddleware
from .services import chesscom


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level, json_logs=settings.env != "development")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database.init_db(settings.database_url)
        await init_redis(settings.redis_url)
        chesscom.init_client(settings.chesscom_contact)
        rt = build_runtime(settings)
        app.state.rt = rt
        await rt.start()
        log.info("startup_complete", env=settings.env, multi_instance=settings.multi_instance)
        try:
            yield
        finally:
            await rt.stop()
            await chesscom.close_client()
            await close_redis()
            await database.close_db()
            log.info("shutdown_complete")

    app = FastAPI(
        title="ShahMaat API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )

    # ---------------------------------------------------------- error handling
    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimited) else None
        return JSONResponse({"error": exc.to_dict()}, status_code=exc.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(x) for x in first.get("loc", [])[1:])
        message = f"{field}: {first.get('msg', 'invalid')}" if field else "Invalid request."
        return JSONResponse({"error": {"code": "validation_error", "message": message}}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", error=type(exc).__name__)
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "Something went wrong."}}, status_code=500
        )

    # ------------------------------------------------------------------ routes
    for router in (auth.router, users.router, games.router, reviews.router, imports.router, puzzles.router):
        app.include_router(router)
    app.include_router(ws_endpoint.router)

    @app.get("/api/health", tags=["ops"])
    async def health() -> dict[str, bool]:
        """Liveness: the process is up. Deliberately touches no database (cheap to poll)."""
        return {"ok": True}

    @app.get("/api/health/ready", tags=["ops"])
    async def ready() -> JSONResponse:
        """Readiness: Postgres and Redis both answer."""
        checks = {"postgres": False, "redis": False}
        try:
            async with database.engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["postgres"] = True
        except Exception:
            log.warning("ready_check_postgres_failed")
        try:
            checks["redis"] = bool(await redis().ping())
        except Exception:
            log.warning("ready_check_redis_failed")
        ok = all(checks.values())
        return JSONResponse({"ok": ok, **checks}, status_code=200 if ok else 503)

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        if (
            settings.metrics_token
            and request.headers.get("authorization") != f"Bearer {settings.metrics_token}"
        ):
            return PlainTextResponse("forbidden", status_code=403)
        if settings.is_production and not settings.metrics_token:
            return PlainTextResponse("not found", status_code=404)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # -------------------------------------------- the React app (production build)
    if settings.web_dist and Path(settings.web_dist, "index.html").exists():
        dist = Path(settings.web_dist).resolve()
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> Response:
            if path.startswith("api/"):
                return JSONResponse(
                    {"error": {"code": "not_found", "message": "Not found."}}, status_code=404
                )
            candidate = (dist / path).resolve()
            # Serve real files (favicon, stockfish.wasm...) but never anything outside dist/.
            if path and candidate.is_file() and candidate.is_relative_to(dist):
                cache = "public, max-age=604800" if path.startswith("stockfish/") else "public, max-age=3600"
                return FileResponse(candidate, headers={"Cache-Control": cache})
            # Every other path is a page of the single-page app.
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    app.add_middleware(SecurityHeadersMiddleware, settings=settings)  # type: ignore[arg-type]
    return app
