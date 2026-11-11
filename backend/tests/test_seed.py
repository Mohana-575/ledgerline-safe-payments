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

from app.models.account import Account
from app.models.user import User
from app.scripts import seed as seed_script
from app.services.ledger import MovementResult


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _seed_records() -> tuple[dict[str, User], dict[str, Account]]:
    admin = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        full_name="Administrator",
        password_hash="hash",
        role="ADMIN",
    )
    holder = User(
        id=uuid.uuid4(),
        email="user1@example.com",
        full_name="User One",
        password_hash="hash",
        role="ACCOUNT_HOLDER",
    )
    accounts = {
        "ACC1001": Account(
            id=21,
            account_number="ACC1001",
            name="Personal",
            type="PERSONAL",
            is_system=False,
            status="ACTIVE",
        ),
        "ACC1002": Account(
            id=22,
            account_number="ACC1002",
            name="Savings",
            type="SAVINGS",
            is_system=False,
            status="ACTIVE",
        ),
    }
    return (
        {
            "admin@example.com": admin,
            "user1@example.com": holder,
        },
        accounts,
    )


def test_seed_uses_idempotent_deposits_with_requested_paise_amounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    users, accounts = _seed_records()
    movements: list[dict[str, object]] = []
    monkeypatch.setattr(seed_script, "_lock_seed", lambda _db: None)
    monkeypatch.setattr(seed_script, "_ensure_external_account", lambda _db: None)
    monkeypatch.setattr(
        seed_script,
        "_get_or_create_users",
        lambda _db, _password, **_kwargs: (users, []),
    )
    monkeypatch.setattr(
        seed_script,
        "_ensure_seed_accounts",
        lambda _db, _holder: accounts,
    )
    monkeypatch.setattr(seed_script, "_assert_reconciled", lambda _db: None)

    def post_movement(_db, actor, kind, **kwargs) -> MovementResult:
        movements.append({"actor": actor, "kind": kind, **kwargs})
        return MovementResult(201, {"transaction_id": "test", "kind": kind})

    monkeypatch.setattr(seed_script, "post_movement", post_movement)

    seed_script.seed(db)  # type: ignore[arg-type]
    seed_script.seed(db)  # type: ignore[arg-type]

    assert db.commits == 2
    assert [movement["amount_paise"] for movement in movements] == [
        7_500_000,
        5_000_000,
        7_500_000,
        5_000_000,
    ]
    assert [movement["to_account_id"] for movement in movements] == [
        21,
        22,
        21,
        22,
    ]
    assert [movement["idempotency_key"] for movement in movements[:2]] == [
        movement["idempotency_key"] for movement in movements[2:]
    ]
    assert all(movement["kind"] == "DEPOSIT" for movement in movements)
    assert all(movement["from_account_id"] is None for movement in movements)


def test_seed_fails_explicitly_when_a_deposit_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    users, accounts = _seed_records()
    monkeypatch.setattr(seed_script, "_lock_seed", lambda _db: None)
    monkeypatch.setattr(seed_script, "_ensure_external_account", lambda _db: None)
    monkeypatch.setattr(
        seed_script,
        "_get_or_create_users",
        lambda _db, _password, **_kwargs: (users, []),
    )
    monkeypatch.setattr(
        seed_script,
        "_ensure_seed_accounts",
        lambda _db, _holder: accounts,
    )
    monkeypatch.setattr(
        seed_script,
        "post_movement",
        lambda *_args, **_kwargs: MovementResult(
            422,
            {"code": "INVALID_AMOUNT", "message": "amount is too large"},
        ),
    )
    monkeypatch.setattr(seed_script, "_assert_reconciled", lambda _db: None)

    with pytest.raises(RuntimeError, match="Deposit to ACC1001 failed: INVALID_AMOUNT"):
        seed_script.seed(db)  # type: ignore[arg-type]


@pytest.mark.parametrize("reset_passwords", [False, True])
def test_existing_seeded_users_are_reset_only_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    reset_passwords: bool,
) -> None:
    users = [
        User(
            email="admin@example.com",
            full_name="Administrator",
            password_hash="old-admin-hash",
            role="ADMIN",
        ),
        User(
            email="auditor@example.com",
            full_name="Auditor",
            password_hash="old-auditor-hash",
            role="AUDITOR",
        ),
        User(
            email="user1@example.com",
            full_name="User One",
            password_hash="old-user-hash",
            role="ACCOUNT_HOLDER",
        ),
    ]

    class ExistingUsersSession:
        def __init__(self) -> None:
            self.users = iter(users)

        def scalar(self, _statement):
            return next(self.users)

    hashed_passwords: list[str] = []

    def hash_password(password: str) -> str:
        hashed_passwords.append(password)
        return f"fresh-hash-{len(hashed_passwords)}"

    monkeypatch.setattr(seed_script, "hash_password", hash_password)

    found_users, generated_credentials = seed_script._get_or_create_users(
        ExistingUsersSession(),  # type: ignore[arg-type]
        "fresh-seed-password",
        reset_passwords=reset_passwords,
    )

    assert generated_credentials == []
    assert set(found_users) == {
        "admin@example.com",
        "auditor@example.com",
        "user1@example.com",
    }
    if reset_passwords:
        assert hashed_passwords == ["fresh-seed-password"] * 3
        assert [user.password_hash for user in users] == [
            "fresh-hash-1",
            "fresh-hash-2",
            "fresh-hash-3",
        ]
    else:
        assert hashed_passwords == []
        assert [user.password_hash for user in users] == [
            "old-admin-hash",
            "old-auditor-hash",
            "old-user-hash",
        ]


def test_reset_passwords_requires_configured_password() -> None:
    with pytest.raises(
        ValueError,
        match="SEED_PASSWORD is required to reset seeded passwords",
    ):
        seed_script.seed(FakeSession(), reset_passwords=True)  # type: ignore[arg-type]
