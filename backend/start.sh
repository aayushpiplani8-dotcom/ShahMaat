#!/bin/sh
# Container entrypoint: bring the database schema up to date, then start the server.
# Migrations run before the server accepts traffic, so code never meets an old schema.
set -e
alembic upgrade head
# One worker on purpose: live WebSocket connections belong to one process. To scale out,
# run more containers with MULTI_INSTANCE=true (they coordinate through Redis).
exec uvicorn shahmaat.main:create_app --factory \
  --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips="*" \
  --timeout-graceful-shutdown 10
