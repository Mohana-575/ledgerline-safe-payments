from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://localhost/ledgerline",
)
os.environ.setdefault("JWT_SECRET", "test-secret-for-ledgerline-32-bytes")
if "TEST_DATABASE_URL" in os.environ:
    TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]
else:
    from pydantic import ValidationError

    from app.core.config import Settings

    try:
        TEST_DATABASE_URL = Settings().TEST_DATABASE_URL
    except ValidationError as exc:
        raise RuntimeError(
            "Configure TEST_DATABASE_URL in the environment or repository .env"
        ) from exc

if not TEST_DATABASE_URL:
    raise RuntimeError(
        "Configure TEST_DATABASE_URL in the environment or repository .env"
    )

if make_url(TEST_DATABASE_URL).database != "ledgerline_test":
    raise RuntimeError(
        "TEST_DATABASE_URL must point to the ledgerline_test database"
    )

os.environ["TEST_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["MIGRATION_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["JWT_SECRET"] = "test-secret-for-ledgerline-32-bytes"
os.environ["COOKIE_SECURE"] = "false"


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database() -> Iterator[None]:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()

    migration_environment = os.environ.copy()
    migration_environment["DATABASE_URL"] = TEST_DATABASE_URL
    migration_environment["TEST_DATABASE_URL"] = TEST_DATABASE_URL
    migration_environment["MIGRATION_DATABASE_URL"] = TEST_DATABASE_URL
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=migration_environment,
        check=True,
    )
    yield


@pytest.fixture
def db_session(migrated_test_database: None) -> Iterator[Session]:
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        yield session


@pytest.fixture(scope="session")
def uvicorn_server(migrated_test_database: None) -> Iterator[str]:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    base_url = f"http://127.0.0.1:{port}"
    server_environment = os.environ.copy()
    server_environment["DATABASE_URL"] = TEST_DATABASE_URL
    server_environment["TEST_DATABASE_URL"] = TEST_DATABASE_URL
    server_environment["MIGRATION_DATABASE_URL"] = TEST_DATABASE_URL
    server_environment["COOKIE_SECURE"] = "false"
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as server_log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=BACKEND_ROOT,
            env=server_environment,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )

        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    with urlopen(f"{base_url}/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except (TimeoutError, URLError):
                    time.sleep(0.1)
            else:
                process.terminate()
                process.wait(timeout=10)

            if process.poll() is not None:
                server_log.seek(0)
                raise RuntimeError(
                    f"Uvicorn exited before becoming healthy:\n{server_log.read()}"
                )

            yield base_url
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
