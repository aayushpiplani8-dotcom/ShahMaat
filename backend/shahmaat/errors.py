"""Application errors.

Code raises an AppError with a stable machine-readable `code` and a safe,
human-readable message. The HTTP layer and the WebSocket layer both turn it into
the same JSON shape, so the frontend handles errors one way everywhere.
Unexpected exceptions are logged in full but the client only sees "internal_error".
"""

from __future__ import annotations


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class NotFound(AppError):
    status = 404
    code = "not_found"


class Unauthorized(AppError):
    status = 401
    code = "unauthorized"


class Forbidden(AppError):
    status = 403
    code = "forbidden"


class Conflict(AppError):
    status = 409
    code = "conflict"


class RateLimited(AppError):
    status = 429
    code = "rate_limited"

    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many requests. Please slow down.")
        self.retry_after = retry_after


class IllegalAction(AppError):
    """A game action that isn't allowed right now (wrong turn, illegal move, game over...)."""

    status = 409
    code = "illegal_action"


class UpstreamError(AppError):
    status = 502
    code = "upstream_error"
