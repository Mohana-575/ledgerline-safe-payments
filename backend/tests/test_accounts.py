from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://localhost/ledgerline")
os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://localhost/ledgerline_test",
)
os.environ.setdefault("JWT_SECRET", "test-secret-for-ledgerline-32-bytes")

import pytest
from app.api.dependencies import current_user
from app.api.routes.accounts import _next_account_number, _visible_account
from app.db.session import get_db
from app.main import app
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.accounts import AccountCreateRequest, MemberAssignRequest
from fastapi import HTTPException
from fastapi.testclient import TestClient


class FakeSequenceSession:
    def __init__(self, account_numbers: list[str]) -> None:
        self.account_numbers = account_numbers
        self.lock_acquired = False

    def execute(self, *_args: object, **_kwargs: object) -> None:
        self.lock_acquired = True

    def scalars(self, _statement: object) -> FakeSequenceSession:
        assert self.lock_acquired
        return self

    def all(self) -> list[str]:
        return self.account_numbers


class FakeAccountCreateSession(FakeSequenceSession):
    def __init__(self, account_numbers: list[str]) -> None:
        super().__init__(account_numbers)
        self.account: Account | None = None
        self.audit_logs: list[AuditLog] = []

    def add(self, instance: object) -> None:
        if isinstance(instance, Account):
            self.account = instance
        elif isinstance(instance, AuditLog):
            self.audit_logs.append(instance)

    def flush(self) -> None:
        assert self.account is not None
        self.account.id = 42

    def commit(self) -> None:
        pass

    def refresh(self, _instance: object) -> None:
        pass


class FakeMemberAssignmentSession:
    def __init__(self, account: Account, user: User) -> None:
        self.account = account
        self.user = user
        self.members: list[AccountMember] = []
        self.audit_logs: list[AuditLog] = []

    def get(self, model: type[object], identity: object) -> object | None:
        if model is Account and identity == self.account.id:
            return self.account
        if model is User and identity == self.user.id:
            return self.user
        if model is AccountMember:
            return None
        return None

    def add(self, instance: object) -> None:
        if isinstance(instance, AccountMember):
            self.members.append(instance)
        elif isinstance(instance, AuditLog):
            self.audit_logs.append(instance)

    def commit(self) -> None:
        pass


def test_account_number_generation_serializes_and_uses_numeric_suffix() -> None:
    session = FakeSequenceSession(["ACC1001", "ACC9999", "other"])

    assert _next_account_number(session) == "ACC10000"  # type: ignore[arg-type]
    assert session.lock_acquired


def test_account_create_schema_is_strict_and_excludes_system_accounts() -> None:
    body = AccountCreateRequest.model_validate(
        {"name": "  Savings  ", "type": "SAVINGS"}
    )
    assert body.name == "Savings"

    for payload in (
        {"name": "Savings", "type": "SYSTEM"},
        {"name": "Savings", "type": "SAVINGS", "role": "ADMIN"},
        {"name": 123, "type": "SAVINGS"},
        {"name": "   ", "type": "SAVINGS"},
    ):
        with pytest.raises(ValueError):
            AccountCreateRequest.model_validate(payload)


def test_member_assignment_schema_accepts_only_uuid_values() -> None:
    user_id = uuid.uuid4()
    assert MemberAssignRequest.model_validate(
        {"user_id": str(user_id)}
    ).user_id == user_id

    for payload in (
        {"user_id": 123},
        {"user_id": "not-a-uuid"},
        {"user_id": str(user_id), "role": "ADMIN"},
    ):
        with pytest.raises(ValueError):
            MemberAssignRequest.model_validate(payload)


def test_invisible_holder_account_is_reported_as_not_found() -> None:
    holder = User(
        id=uuid.uuid4(),
        email="holder@example.com",
        full_name="Account Holder",
        password_hash="not-returned",
        role="ACCOUNT_HOLDER",
    )

    class NoAccountSession:
        def scalar(self, _statement: object) -> None:
            return None

    with pytest.raises(HTTPException) as error:
        _visible_account(NoAccountSession(), holder, 123)  # type: ignore[arg-type]
    assert error.value.status_code == 404


def test_admin_can_create_account_with_audit_log() -> None:
    admin = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        full_name="Admin",
        password_hash="never-returned",
        role="ADMIN",
    )
    db = FakeAccountCreateSession(["ACC1001"])

    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).post(
            "/accounts",
            json={"name": "  Savings  ", "type": "SAVINGS"},
        )
    finally:
        app.dependency_overrides.pop(current_user)
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 201
    assert response.json() == {
        "id": 42,
        "account_number": "ACC1002",
        "name": "Savings",
        "type": "SAVINGS",
        "balance_paise": 0,
        "status": "ACTIVE",
    }
    assert "password_hash" not in response.json()
    assert len(db.audit_logs) == 1
    assert db.audit_logs[0].action == "ACCOUNT_CREATED"
    assert db.audit_logs[0].user_id == admin.id
    assert db.audit_logs[0].details == {
        "account_id": "42",
        "account_number": "ACC1002",
    }


def test_admin_can_assign_member_with_audit_log() -> None:
    admin = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        full_name="Admin",
        password_hash="never-returned",
        role="ADMIN",
    )
    member = User(
        id=uuid.uuid4(),
        email="holder@example.com",
        full_name="Holder",
        password_hash="never-returned",
        role="ACCOUNT_HOLDER",
    )
    account = Account(
        id=42,
        account_number="ACC1002",
        name="Savings",
        type="SAVINGS",
        balance_paise=0,
        is_system=False,
        status="ACTIVE",
    )
    db = FakeMemberAssignmentSession(account, member)

    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).post(
            "/accounts/42/members",
            json={"user_id": str(member.id)},
        )
    finally:
        app.dependency_overrides.pop(current_user)
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 201
    assert response.json() == {"account_id": 42, "user_id": str(member.id)}
    assert len(db.members) == 1
    assert db.members[0].account_id == 42
    assert db.members[0].user_id == member.id
    assert len(db.audit_logs) == 1
    assert db.audit_logs[0].action == "MEMBER_ASSIGNED"
    assert db.audit_logs[0].user_id == admin.id
    assert db.audit_logs[0].details == {
        "account_id": "42",
        "user_id": str(member.id),
    }


def test_account_creation_requires_database_admin_role() -> None:
    user = User(
        id=uuid.uuid4(),
        email="holder@example.com",
        full_name="Account Holder",
        password_hash="not-returned",
        role="ACCOUNT_HOLDER",
    )

    def override_current_user() -> User:
        return user

    def override_get_db() -> object:
        return object()

    app.dependency_overrides[current_user] = override_current_user
    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/accounts",
            json={"name": "Savings", "type": "SAVINGS"},
        )
    finally:
        app.dependency_overrides.pop(current_user)
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 403
