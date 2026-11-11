# LedgerLine

LedgerLine is a monorepo with a FastAPI backend and a React frontend.

## Repository layout

- `backend/` — Python API managed with uv.
- `frontend/` — Vite, React, and TypeScript application.
- `docker-compose.yml` — local PostgreSQL service.

## Prerequisites

- Python 3.13 or newer and [uv](https://docs.astral.sh/uv/)
- Node.js and npm
- Docker Compose

## Local setup

Copy `.env.example` to `.env`, then start PostgreSQL:

```powershell
Copy-Item .env.example .env
docker compose up -d
```

The database initialization script creates `ledgerline_test` alongside the
`ledgerline` database.

Install backend dependencies and start the API:

```powershell
Set-Location backend
uv sync
uv run alembic upgrade head
uv run python -m app.scripts.seed
uv run uvicorn app.main:app --reload
```

The seed command creates the example admin, auditor, and account-holder users,
the holder's Personal and Savings accounts, and funds them through the ledger.
Set `SEED_PASSWORD` before running it to use one password for newly created
users. If it is unset, unique passwords are generated and printed once; save
them securely. The command can be rerun safely.
To reset the passwords of existing seeded users, set `SEED_PASSWORD` and rerun
the command with `--reset-passwords`; without that flag, existing passwords are
left unchanged.

The API health check is available at `GET /health`.

## Backend tests

Run the backend tests from `backend/` with `uv run pytest`. The test session
drops and recreates the `public` schema in `ledgerline_test`, then runs Alembic
migrations once. Configure `TEST_DATABASE_URL` to point to that database before
running tests; do not point it at a development or production database.

The optional least-privilege database role can be created by running
`psql -d ledgerline -f scripts/create_app_role.sql` from the repository root.
The script prompts for the role password.

Install frontend dependencies and start Vite in another terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

## Render and Neon deployment

The root `Dockerfile` builds the frontend and backend into one non-root image.
Render uses `render.yaml` and checks `GET /health`. The Docker command applies
Alembic migrations before starting FastAPI. It does not seed the database.

Set `DATABASE_URL` to Neon’s pooled connection URL (the hostname includes
`-pooler`) using SQLAlchemy’s `postgresql+psycopg://` driver and TLS, such as
`sslmode=require`. Set `MIGRATION_DATABASE_URL` to the direct, non-pooled Neon
URL for schema migrations. Render generates `JWT_SECRET`; neither database URL
nor the secret belongs in source control. `TEST_DATABASE_URL` is optional at
application startup but pytest requires it to point to a separate
non-production database named `ledgerline_test`.

On Render Free, startup migrations run in the single service instance before
Uvicorn; expect deployment downtime and keep migrations backward-compatible.
On a paid multi-instance service, use Render’s pre-deploy command for
`alembic upgrade head` and set the service start command to
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`. This runs migrations once
before new instances start and avoids concurrent per-instance migration runs.
Use a Neon backup/branch before schema changes.

## Validation

Run backend checks from `backend/`:

```powershell
uv run ruff check .
uv run pytest
```

Run the frontend production build from `frontend/`:

```powershell
npm run build
```
