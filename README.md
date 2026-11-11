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
