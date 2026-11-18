"""All configuration comes from environment variables (or a .env file in development).

Pydantic validates every value at startup, so a missing secret or a malformed URL
stops the server immediately with a clear message instead of failing mid-game.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["development", "test", "production"] = "development"

    # --- Infrastructure -------------------------------------------------
    database_url: str = "postgresql+asyncpg://shahmaat:shahmaat@localhost:5432/shahmaat"
    redis_url: str = "redis://localhost:6379/0"
    # When true, game updates travel through Redis pub/sub so 2+ server instances
    # can share players. One instance doesn't need it, and skipping it saves Redis
    # commands (which matters on free tiers that count every command).
    multi_instance: bool = False

    # --- Security -------------------------------------------------------
    jwt_secret: str = Field(min_length=32)
    refresh_token_secret: str = Field(min_length=32)
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_days: int = 30
    app_origin: str = "http://localhost:5173"
    trust_proxy: bool = False
    metrics_token: str | None = None

    # --- Google sign-in (optional) ---------------------------------------
    google_client_id: str | None = None
    google_client_secret: str | None = None

    # --- chess.com ----------------------------------------------------------
    chesscom_contact: str = "unknown"

    # --- Misc -------------------------------------------------------------
    log_level: str = "INFO"
    web_dist: str | None = None  # folder with the built React app; served when set
    port: int = 8000

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        # Hosting providers hand out "postgres://..." URLs; SQLAlchemy needs the async driver named.
        if v.startswith("postgres://"):
            v = "postgresql://" + v.removeprefix("postgres://")
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v.removeprefix("postgresql://")
        # Neon/Render URLs carry libpq options (sslmode, channel_binding) that the
        # asyncpg driver doesn't understand; translate sslmode and drop the rest.
        parts = urlsplit(v)
        if parts.query:
            query = []
            for key, value in parse_qsl(parts.query):
                if key == "sslmode":
                    query.append(("ssl", value))
                elif key != "channel_binding":
                    query.append((key, value))
            v = urlunsplit(parts._replace(query=urlencode(query)))
        return v

    @field_validator("app_origin")
    @classmethod
    def _no_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @model_validator(mode="after")
    def _secrets_differ(self) -> Settings:
        if self.jwt_secret == self.refresh_token_secret:
            raise ValueError("JWT_SECRET and REFRESH_TOKEN_SECRET must be different")
        if bool(self.google_client_id) != bool(self.google_client_secret):
            raise ValueError("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET together (or neither)")
        return self

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def secure_cookies(self) -> bool:
        return self.app_origin.startswith("https://")

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
