"""Structured JSON logs (one JSON object per line) with secrets redacted.

JSON logs can be searched and filtered by any log service ("show every error for
game abc123") instead of grepping free text.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_SECRET_KEYS = {
    "password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "secret",
    "code",
}


def _redact(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event):
        if key.lower() in _SECRET_KEYS:
            event[key] = "[redacted]"
    return event


def setup_logging(level: str = "INFO", json_logs: bool = True) -> None:
    renderer: Any = structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    # Route the standard library's loggers (uvicorn, sqlalchemy) to the same stream.
    logging.basicConfig(stream=sys.stdout, level=level.upper(), format="%(message)s")
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


log = structlog.get_logger("shahmaat")
