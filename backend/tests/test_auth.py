import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://localhost/ledgerline")
os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://localhost/ledgerline_test",
)
os.environ.setdefault("JWT_SECRET", "test-secret-for-ledgerline-32-bytes")

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import app.api.routes.auth as auth_routes
from app.core.security import decode_access_token, verify_password
from app.db.session import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.user import User


class FakeAuthSession:
    def __init__(self) -> None:
        self.user: User | None = None
        self.audit_logs: list[AuditLog] = []

    def scalar(self, statement: object) -> User | uuid.UUID | None:
        if self.user is None:
            return None

        parameters = statement.compile().params.values()
        if self.user.email not in parameters and self.user.id not in parameters:
            return None

        columns = getattr(statement, "column_descriptions", [])
        if columns and columns[0]["name"] == "id":
            return self.user.id
        return self.user

    def add(self, instance: object) -> None:
        if isinstance(instance, User):
            self.user = instance
        elif isinstance(instance, AuditLog):
            self.audit_logs.append(instance)

    def flush(self) -> None:
        if self.user is not None and self.user.id is None:
            self.user.id = uuid.uuid4()

    def commit(self) -> None:
        pass

    def refresh(self, _instance: object) -> None:
        pass

    def rollback(self) -> None:
        pass


def test_register_login_logout_and_current_user() -> None:
    db = FakeAuthSession()

    def override_get_db() -> FakeAuthSession:
        return db

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app, base_url="https://testserver")
        role_injection = client.post(
            "/auth/register",
            json={
                "full_name": "A. Holder",
                "email": "holder@example.com",
                "password": "correct horse battery staple",
                "role": "ADMIN",
            },
        )
        assert role_injection.status_code == 422

        registration = client.post(
            "/auth/register",
            json={
                "full_name": " A. Holder ",
                "email": "HOLDER@example.com",
                "password": "correct horse battery staple",
            },
        )
        assert registration.status_code == 201
        assert registration.json()["role"] == "ACCOUNT_HOLDER"
        assert registration.json()["full_name"] == "A. Holder"
        assert db.user is not None
        assert db.user.email == "holder@example.com"
        assert verify_password("correct horse battery staple", db.user.password_hash)
        assert [entry.action for entry in db.audit_logs] == ["REGISTER"]

        bad_password = client.post(
            "/auth/login",
            json={
                "email": "holder@example.com",
                "password": "wrong password",
            },
        )
        unknown_email = client.post(
            "/auth/login",
            json={"email": "missing@example.com", "password": "wrong password"},
        )
        assert bad_password.status_code == unknown_email.status_code == 401
        assert bad_password.json() == unknown_email.json()

        login = client.post(
            "/auth/login",
            json={
                "email": "holder@example.com",
                "password": "correct horse battery staple",
            },
        )
        assert login.status_code == 200
        cookie = login.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "secure" in cookie
        assert "samesite=strict" in cookie
        assert decode_access_token(client.cookies["access_token"]) == db.user.id
        assert [entry.action for entry in db.audit_logs] == [
            "REGISTER",
            "LOGIN_FAILED",
            "LOGIN_FAILED",
            "LOGIN_SUCCESS",
        ]

        db.user.role = "AUDITOR"
        assert client.get("/auth/me").json()["role"] == "AUDITOR"

        logout = client.post("/auth/logout")
        assert logout.status_code == 204
        assert client.get("/auth/me").status_code == 401
    finally:
        app.dependency_overrides.pop(get_db)


def test_unknown_email_uses_dummy_password_verification_and_generic_response(
    monkeypatch: MonkeyPatch,
) -> None:
    db = FakeAuthSession()
    monkeypatch.setitem(auth_routes._RATE_LIMITS, "login", 10)
    auth_routes._rate_attempts.clear()
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        registration = client.post(
            "/auth/register",
            json={
                "full_name": "A. Holder",
                "email": "holder@example.com",
                "password": "correct horse battery staple",
            },
        )
        assert registration.status_code == 201
        assert db.user is not None

        verified_hashes: list[str] = []
        real_verify_password = auth_routes.verify_password

        def verify_and_record(password: str, password_hash: str) -> bool:
            verified_hashes.append(password_hash)
            return real_verify_password(password, password_hash)

        monkeypatch.setattr(auth_routes, "verify_password", verify_and_record)
        request = {"password": "wrong password"}
        wrong_password = client.post(
            "/auth/login",
            json={"email": "holder@example.com", **request},
        )
        unknown_email = client.post(
            "/auth/login",
            json={"email": "missing@example.com", **request},
        )

        assert wrong_password.status_code == unknown_email.status_code == 401
        assert wrong_password.json() == unknown_email.json()
        assert len(verified_hashes) == 2
        assert verified_hashes == [
            db.user.password_hash,
            auth_routes._DUMMY_PASSWORD_HASH,
        ]
    finally:
        app.dependency_overrides.pop(get_db)
        auth_routes._rate_attempts.clear()


def test_login_is_rate_limited(monkeypatch: MonkeyPatch) -> None:
    db = FakeAuthSession()

    def override_get_db() -> FakeAuthSession:
        return db

    monkeypatch.setitem(auth_routes._RATE_LIMITS, "login", 1)
    auth_routes._rate_attempts.clear()
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        request = {
            "email": "missing@example.com",
            "password": "wrong password",
        }
        assert client.post("/auth/login", json=request).status_code == 401
        limited = client.post("/auth/login", json=request)
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) > 0
    finally:
        app.dependency_overrides.pop(get_db)
        auth_routes._rate_attempts.clear()
