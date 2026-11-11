import os

from pytest import MonkeyPatch

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://ledgerline:ledgerline_dev_password@localhost:5432/ledgerline",
)
os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://ledgerline:ledgerline_dev_password@localhost:5432/ledgerline_test",
)
os.environ.setdefault("JWT_SECRET", "test-secret-for-ledgerline")

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.session import get_db
from app.main import app


class FakeSession:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.statement: str | None = None

    def execute(self, statement: object) -> None:
        self.statement = str(statement)
        if self.fail:
            raise RuntimeError("database unavailable")


def test_runtime_settings_do_not_require_test_database_url(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://user:pass@localhost/app",
        JWT_SECRET="a-test-secret-long-enough-for-settings",
    )

    assert settings.TEST_DATABASE_URL is None


def test_health_check_executes_select_one() -> None:
    session = FakeSession()

    def override_get_db() -> FakeSession:
        return session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert session.statement == "SELECT 1"


def test_health_database_error_uses_standard_error_response() -> None:
    def override_get_db() -> FakeSession:
        return FakeSession(fail=True)

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app, raise_server_exceptions=False).get("/health")
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "An unexpected error occurred",
    }
