# ---- Stage 1: build the React app ------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: the Python server (serves the API, WebSockets and the built app)
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# Install dependencies first (cached layer: only rebuilt when pyproject.toml changes).
COPY backend/pyproject.toml ./
COPY backend/shahmaat ./shahmaat
RUN pip install .

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/start.sh ./start.sh
COPY --from=web /web/dist ./web
# Git on Windows doesn't keep the "executable" flag, so set it here.
RUN chmod +x ./start.sh

# Never run as root inside the container.
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

ENV ENV=production WEB_DIST=/app/web PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health', timeout=2)"
CMD ["sh", "./start.sh"]
