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
from app.api.routes import admin as admin_routes
from app.db.session import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.user import User
from fastapi.testclient import TestClient


class FakeResult:
    def __init__(
        self,
        *,
        rows: list[tuple[object, ...]] | None = None,
        mappings: list[dict[str, object]] | None = None,
    ) -> None:
        self.rows = rows or []
        self.mapping_rows = mappings or []

    def all(self) -> list[object]:
        return self.mapping_rows if self.mapping_rows else self.rows

    def mappings(self) -> FakeResult:
        return self

    def __iter__(self):
        return iter(self.mapping_rows)


class FakeScalarRows:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class FakeSession:
    def __init__(self) -> None:
        self.scalar_values: list[object] = []
        self.account_rows: list[tuple[object, ...]] = []
        self.negative_rows: list[tuple[object, ...]] = []
        self.transaction_rows: list[tuple[object, ...]] = []
        self.recent_rows: list[dict[str, object]] = []
        self.account_ids: list[int] = [1, 2]
        self.member_account_ids: list[int] = [1, 2]
        self.audit_logs: list[AuditLog] = []
        self.commits = 0
        self.statements: list[str] = []

    def scalar(self, _statement: object) -> object:
        return self.scalar_values.pop(0)

    def scalars(self, statement: object) -> FakeScalarRows:
        query = str(statement)
        if "account_members.account_id" in query:
            return FakeScalarRows(self.member_account_ids)
        if "accounts.id" in query:
            return FakeScalarRows(self.account_ids)
        return FakeScalarRows([])

    def execute(self, statement: object) -> FakeResult:
        query = str(statement)
        self.statements.append(query)
        if "GROUP BY accounts.id" in query:
            return FakeResult(rows=self.account_rows)
        if "accounts.is_system IS false" in query:
            return FakeResult(rows=self.negative_rows)
        if "GROUP BY transactions.id" in query:
            return FakeResult(rows=self.transaction_rows)
        if "ranked_user_transactions" in query:
            return FakeResult(mappings=self.recent_rows)
        raise AssertionError(f"Unexpected query: {query}")

    def add(self, instance: object) -> None:
        assert isinstance(instance, AuditLog)
        self.audit_logs.append(instance)

    def commit(self) -> None:
        self.commits += 1


def _user(role: str) -> User:
    return User(
        id=uuid.uuid4(),
        email="operator@example.com",
        full_name="Operator",
        password_hash="never-returned",
        role=role,
    )


def test_reconcile_reports_actual_mismatches_and_audits_run() -> None:
    actor = _user("AUDITOR")
    db = FakeSession()
    db.scalar_values = [0]
    transaction_id = uuid.uuid4()
    db.account_rows = [
        (1, "ACC0001", 100, 100),
        (2, "ACC1001", -100, -90),
    ]
    db.negative_rows = [(2, "ACC1001", -100)]
    db.transaction_rows = [(transaction_id, 200, 190)]
    app.dependency_overrides[current_user] = lambda: actor
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).get("/admin/reconcile")
    finally:
        app.dependency_overrides.pop(current_user)
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["passed"] is False
    assert body["account_balance_sum_paise"] == 0
    assert body["accounts_sum_to_zero"] is True
    assert body["accounts_match_ledger"] is False
    assert body["non_system_accounts_nonnegative"] is False
    assert body["transactions_balanced"] is False
    assert body["account_mismatches"] == [
        {
            "account_id": 2,
            "account_number": "ACC1001",
            "balance_paise": -100,
            "ledger_balance_paise": -90,
        }
    ]
    assert body["negative_accounts"][0]["balance_paise"] == -100
    assert body["transaction_mismatches"] == [
        {
            "transaction_id": str(transaction_id),
            "debits_paise": 200,
            "credits_paise": 190,
        }
    ]
    assert db.commits == 1
    assert db.audit_logs[0].action == "RECONCILIATION_RUN"
    assert db.audit_logs[0].user_id == actor.id


def test_admin_routes_reject_account_holder() -> None:
    holder = _user("ACCOUNT_HOLDER")
    app.dependency_overrides[current_user] = lambda: holder
    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app)
        reconcile = client.get("/admin/reconcile")
        verify = client.get("/admin/verify-ledger")
    finally:
        app.dependency_overrides.pop(current_user)
        app.dependency_overrides.pop(get_db)

    assert reconcile.status_code == 403
    assert verify.status_code == 403


def test_verify_ledger_returns_broken_entry_and_audits_run(monkeypatch) -> None:
    actor = _user("ADMIN")
    db = FakeSession()
    db.account_ids = [2, 4]
    monkeypatch.setattr(
        admin_routes,
        "verify_chain",
        lambda _db, account_id: 71 if account_id == 4 else None,
    )
    app.dependency_overrides[current_user] = lambda: actor
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).get("/admin/verify-ledger")
    finally:
        app.dependency_overrides.pop(current_user)
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert response.json() == {
        "passed": False,
        "accounts_checked": 2,
        "accounts": [
            {"account_id": 2, "passed": True, "first_broken_entry_id": None},
            {"account_id": 4, "passed": False, "first_broken_entry_id": 71},
        ],
    }
    assert db.commits == 1
    assert db.audit_logs[0].action == "LEDGER_VERIFICATION_RUN"


def test_dashboard_uses_only_member_accounts_and_returns_real_activity() -> None:
    user = _user("ACCOUNT_HOLDER")
    transaction_id = uuid.uuid4()
    db = FakeSession()
    db.member_account_ids = [12]
    db.scalar_values = [3, 4250]
    db.recent_rows = [
        {
            "transaction_id": transaction_id,
            "type": "DEPOSIT",
            "date_time": datetime(2026, 11, 8, 8, 30, tzinfo=UTC),
            "account_id": 12,
            "direction": "CREDIT",
            "amount_paise": 250,
            "balance_after_paise": 4250,
            "entry_rank": 1,
        }
    ]
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).get("/dashboard")
    finally:
        app.dependency_overrides.pop(current_user)
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert response.json() == {
        "total_balance_paise": 4250,
        "account_count": 1,
        "transactions_last_30_days": 3,
        "role": "ACCOUNT_HOLDER",
        "recent_transactions": [
            {
                "transaction_id": str(transaction_id),
                "type": "DEPOSIT",
                "date_time": "2026-11-08T08:30:00Z",
                "account_id": 12,
                "direction": "CREDIT",
                "amount_paise": 250,
                "balance_after_paise": 4250,
            }
        ],
    }
    assert not db.audit_logs
    assert db.commits == 0
