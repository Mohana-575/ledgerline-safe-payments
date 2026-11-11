FROM ghcr.io/astral-sh/uv:0.11.23 AS uv-bin

FROM node:22-bookworm-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS backend-dependencies
COPY --from=uv-bin /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.13-slim AS runtime
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app/backend

RUN groupadd --system --gid 10001 ledgerline \
    && useradd --system --uid 10001 --gid ledgerline \
        --home-dir /home/ledgerline --create-home \
        --shell /usr/sbin/nologin ledgerline

COPY --from=backend-dependencies --chown=ledgerline:ledgerline /opt/venv /opt/venv
COPY --chown=ledgerline:ledgerline backend/app ./app
COPY --chown=ledgerline:ledgerline backend/alembic ./alembic
COPY --chown=ledgerline:ledgerline backend/alembic.ini ./alembic.ini
COPY --from=frontend-build --chown=ledgerline:ledgerline /frontend/dist ./app/static

USER ledgerline
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT', '10000'), timeout=4)"]
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-10000}\""]
