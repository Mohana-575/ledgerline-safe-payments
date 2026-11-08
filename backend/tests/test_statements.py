from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://localhost/ledgerline")
os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://localhost/ledgerline_test",
)
os.environ.setdefault("JWT_SECRET", "test-secret-for-ledgerline-32-bytes")

from app.api.dependencies import current_user
from app.api.routes.statements import _statement_query
from app.db.session import get_db
from app.main import app
from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.user import User
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql


class FakeResult:
    def __init__(
        self,
        *,
        mappings: list[dict[str, object]] | None = None,
        rows: list[tuple[object, ...]] | None = None,
    ) -> None:
        self._mappings = mappings or []
        self._rows = rows or []

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[object]:
        return self._mappings if self._mappings else self._rows


class FakeReadSession:
    def __init__(
        self,
        *,
        account: Account | None = None,
        statement_rows: list[dict[str, object]] | None = None,
        audit_rows: list[tuple[object, ...]] | None = None,
    ) -> None:
        self.account = account
        self.statement_rows = statement_rows or []
        self.audit_rows = audit_rows or []
        self.statements: list[object] = []
        self.writes = 0

    def scalar(self, _statement: object) -> Account | None:
        return self.account

    def execute(self, statement: object) -> FakeResult:
        self.statements.append(statement)
        if "statement_rows" in str(statement):
            return FakeResult(mappings=self.statement_rows)
        return FakeResult(rows=self.audit_rows)

    def add(self, _instance: object) -> None:
        self.writes += 1

    def commit(self) -> None:
        self.writes += 1


def _account() -> Account:
    return Account(
        id=7,
        account_number="ACC0007",
        name="Savings",
        type="SAVINGS",
        balance_paise=1000,
        is_system=False,
        status="ACTIVE",
    )


def _user(role: str) -> User:
    return User(
        id=uuid.uuid4(),
        email="viewer@example.com",
        full_name="Viewer",
        password_hash="never-returned",
        role=role,
    )


def test_statement_query_merges_refusals_and_filters_type_and_date() -> None:
    query = _statement_query(
        7,
        statement_type="ALL",
        from_time=datetime(2026, 11, 1, tzinfo=UTC),
        to_time=datetime(2026, 11, 30, tzinfo=UTC),
        cursor=None,
    )
    compiled = str(query.compile(dialect=postgresql.dialect()))

    assert "UNION ALL" in compiled
    assert "refused_attempts" in compiled
    assert "ledger_entries" in compiled
    assert "ORDER BY statement_rows.date_time, statement_rows.source, statement_rows.row_id" in compiled
    assert "refused_attempts.created_at" in compiled


def test_statement_returns_ledger_and_refused_rows_with_actor_details() -> None:
    actor = _user("ADMIN")
    moment = datetime(2026, 11, 8, 8, 30, tzinfo=UTC)
    db = FakeReadSession(
        account=_account(),
        statement_rows=[
            {
                "source": "L",
                "row_id": 1,
                "date_time": moment,
                "type": "DEPOSIT",
                "amount_paise": 100,
                "running_balance_paise": 100,
                "status": "COMPLETED",
                "reason_code": None,
                "initiated_by_name": "Viewer",
                "initiated_by_email": "viewer@example.com",
            },
            {
                "source": "R",
                "row_id": 2,
                "date_time": moment,
                "type": "REFUSED",
                "amount_paise": -200,
                "running_balance_paise": 100,
                "status": "REFUSED",
                "reason_code": "INSUFFICIENT_FUNDS",
                "initiated_by_name": "Viewer",
                "initiated_by_email": "viewer@example.com",
            },
        ],
    )
    app.dependency_overrides[current_user] = lambda: actor
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).get("/accounts/7/statement")
    finally:
        app.dependency_overrides.pop(current_user)
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert [row["type"] for row in body["items"]] == ["DEPOSIT", "REFUSED"]
    assert [row["amount_paise"] for row in body["items"]] == [100, -200]
    assert [row["running_balance_paise"] for row in body["items"]] == [100, 100]
    assert body["items"][1]["reason_code"] == "INSUFFICIENT_FUNDS"
    assert body["items"][0]["initiated_by"] == {
        "name": "Viewer",
        "email": "viewer@example.com",
    }
    assert db.writes == 0


def test_holder_cannot_read_nonmember_statement() -> None:
    holder = _user("ACCOUNT_HOLDER")
    db = FakeReadSession(account=None)
    app.dependency_overrides[current_user] = lambda: holder
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).get("/accounts/7/statement")
    finally:
        app.dependency_overrides.pop(current_user)
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404
    assert not db.statements


def test_statement_cursor_and_timezone_ranges_are_validated() -> None:
    admin = _user("ADMIN")
    db = FakeReadSession(account=_account())
    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[get_db] = lambda: db
    try:
        invalid_cursor = TestClient(app).get(
            "/accounts/7/statement",
            params={"cursor": "not-a-cursor"},
        )
        naive_date = TestClient(app).get(
            "/accounts/7/statement",
            params={"from": "2026-11-08T08:30:00"},
        )
    finally:
        app.dependency_overrides.pop(current_user)
        app.dependency_overrides.pop(get_db)

    assert invalid_cursor.status_code == 400
    assert naive_date.status_code == 422


def test_audit_logs_are_scoped_for_holders_and_global_for_admins() -> None:
    holder = _user("ACCOUNT_HOLDER")
    admin = _user("ADMIN")
    audit = AuditLog(
        id=9,
        user_id=holder.id,
        action="DEPOSIT",
        details={"amount_paise": "100"},
        ip="127.0.0.1",
        created_at=datetime(2026, 11, 8, 8, 30, tzinfo=UTC),
    )
    db = FakeReadSession(audit_rows=[(audit, holder.full_name, holder.email)])

    app.dependency_overrides[current_user] = lambda: holder
    app.dependency_overrides[get_db] = lambda: db
    try:
        holder_response = TestClient(app).get("/audit-logs")
        holder_query = str(db.statements[-1])

        app.dependency_overrides[current_user] = lambda: admin
        admin_response = TestClient(app).get("/audit-logs")
        admin_query = str(db.statements[-1])
    finally:
        app.dependency_overrides.pop(current_user)
        app.dependency_overrides.pop(get_db)

    assert holder_response.status_code == 200
    assert holder_response.json()["items"][0]["initiated_by"]["email"] == holder.email
    assert "WHERE audit_logs.user_id =" in holder_query
    assert admin_response.status_code == 200
    assert "WHERE audit_logs.user_id =" not in admin_query
    assert db.writes == 0
