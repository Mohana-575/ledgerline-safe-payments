from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://localhost/ledgerline")
os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://localhost/ledgerline_test",
)
os.environ.setdefault("JWT_SECRET", "test-secret-for-ledgerline-32-bytes")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Select

from app.api.dependencies import current_user
from app.db.session import get_db
from app.main import app
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.audit_log import AuditLog
from app.models.ledger_entry import LedgerEntry
from app.models.transaction import Transaction
from app.models.user import User
from app.services.ledger import post_movement
from app.services.ledger_errors import (
    AccountFrozenError,
    AccountNotFoundError,
    ForbiddenMovementError,
    InsufficientFundsError,
    InvalidAmountError,
)
from app.services.verify import verify_chain


class FakeResult:
    def __init__(
        self,
        *,
        first_value: object | None = None,
        rowcount: int = 0,
        mapping: dict[str, object] | None = None,
    ) -> None:
        self.first_value = first_value
        self.rowcount = rowcount
        self.mapping = mapping

    def first(self) -> object | None:
        return self.first_value

    def mappings(self) -> FakeResult:
        return self

    def one(self) -> dict[str, object]:
        assert self.mapping is not None
        return self.mapping


class FakeScalarRows:
    def __init__(self, values: list[Account]) -> None:
        self.values = values

    def all(self) -> list[Account]:
        return self.values


class FakeEntryRows:
    def __init__(self, values: list[LedgerEntry]) -> None:
        self.values = values

    def all(self) -> list[LedgerEntry]:
        return self.values


class FakeVerifySession:
    def __init__(self, entries: list[LedgerEntry]) -> None:
        self.entries = entries

    def scalars(self, _statement: Select[tuple[LedgerEntry]]) -> FakeEntryRows:
        return FakeEntryRows(
            sorted(self.entries, key=lambda entry: entry.id)
        )


def _expected_entry_hash(entry: LedgerEntry) -> str:
    payload = json.dumps(
        {
            "prev_hash": entry.prev_hash,
            "txn_id": str(entry.txn_id),
            "account_id": entry.account_id,
            "direction": entry.direction,
            "amount_paise": entry.amount_paise,
            "balance_after_paise": entry.balance_after_paise,
            "created_at": entry.created_at.astimezone(UTC).isoformat(),
            "initiated_by": str(entry.initiated_by),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class FakeSession:
    def __init__(
        self,
        accounts: list[Account],
        *,
        role: str = "ACCOUNT_HOLDER",
        member_account_ids: set[int] | None = None,
        membership_results: list[uuid.UUID | None] | None = None,
    ) -> None:
        self.accounts = {account.id: account for account in accounts}
        self.role = role
        self.member_account_ids = member_account_ids or set()
        self.membership_results = membership_results
        self.membership_statements: list[str] = []
        self.external_lookups = 0
        self.account_lock_statement: Select[tuple[Account]] | None = None
        self.added: list[object] = []
        self.committed = False
        self.rolled_back = False
        self.transaction_started = False
        self.idempotency_rows: dict[tuple[uuid.UUID, str], dict[str, object]] = {}
        self.refused_attempts: list[dict[str, object]] = []
        self.sql_log: list[str] = []

    def in_transaction(self) -> bool:
        return self.transaction_started

    def begin(self) -> None:
        self.transaction_started = True

    def execute(
        self,
        statement: object,
        parameters: dict[str, object],
    ) -> FakeResult:
        query = str(statement)
        self.sql_log.append(query)
        if "INSERT INTO idempotency_keys" in query:
            identity = (parameters["user_id"], parameters["key"])
            if identity in self.idempotency_rows:
                return FakeResult()
            self.idempotency_rows[identity] = {
                "request_hash": parameters["request_hash"],
                "status": "PENDING",
                "response_status": None,
                "response_body": None,
            }
            return FakeResult(first_value=(parameters["key"],))
        if "SELECT request_hash, status, response_status, response_body" in query:
            row = self.idempotency_rows[
                (parameters["user_id"], parameters["key"])
            ]
            return FakeResult(mapping=row)
        if "UPDATE idempotency_keys" in query:
            row = self.idempotency_rows[
                (parameters["user_id"], parameters["key"])
            ]
            row["status"] = parameters["status"]
            row["response_status"] = parameters["response_status"]
            row["response_body"] = json.loads(parameters["response_body"])
            return FakeResult(rowcount=1)
        if "INSERT INTO refused_attempts" in query:
            self.refused_attempts.append(parameters.copy())
            return FakeResult(rowcount=1)
        raise AssertionError(f"Unexpected SQL statement: {query}")

    def scalar(self, statement: Select[tuple[object]]) -> object:
        entity = statement.column_descriptions[0]["entity"]
        column_name = statement.column_descriptions[0]["name"]
        if entity is Account and column_name == "id":
            if "account_number" in str(statement):
                self.external_lookups += 1
                return next(
                    (
                        account.id
                        for account in self.accounts.values()
                        if account.account_number == "ACC1001" and account.is_system
                    ),
                    None,
                )
            account_id = next(
                parameter
                for parameter in statement.compile().params.values()
                if type(parameter) is int
            )
            return account_id if account_id in self.accounts else None
        if entity is Account and column_name == "is_system":
            account_id = next(
                parameter
                for parameter in statement.compile().params.values()
                if type(parameter) is int
            )
            account = self.accounts.get(account_id)
            return account.is_system if account is not None else None
        if entity is User and column_name == "role":
            return self.role
        if entity is AccountMember and column_name == "user_id":
            self.membership_statements.append(str(statement))
            if self.membership_results is not None:
                return self.membership_results.pop(0)
            account_id = next(
                parameter
                for parameter in statement.compile().params.values()
                if type(parameter) is int
            )
            return (
                uuid.uuid4()
                if account_id in self.member_account_ids
                else None
            )
        raise AssertionError(f"Unexpected scalar query: {statement}")

    def scalars(self, statement: Select[tuple[Account]]) -> FakeScalarRows:
        self.account_lock_statement = statement
        account_ids = {
            account_id
            for parameter in statement.compile().params.values()
            for account_id in (
                parameter if isinstance(parameter, (list, tuple)) else [parameter]
            )
            if type(account_id) is int
        }
        return FakeScalarRows(
            [self.accounts[account_id] for account_id in sorted(account_ids)
             if account_id in self.accounts]
        )

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def add_all(self, instances: list[object] | tuple[object, ...]) -> None:
        self.added.extend(instances)

    def flush(self) -> None:
        for index, instance in enumerate(self.added):
            if isinstance(instance, Transaction) and instance.id is None:
                instance.id = uuid.uuid4()
            elif isinstance(instance, LedgerEntry) and instance.id is None:
                instance.id = 100 + index

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def _account(
    account_id: int,
    account_number: str,
    balance_paise: int,
    *,
    is_system: bool = False,
    status: str = "ACTIVE",
) -> Account:
    return Account(
        id=account_id,
        account_number=account_number,
        name=account_number,
        type="SYSTEM" if is_system else "SAVINGS",
        balance_paise=balance_paise,
        is_system=is_system,
        status=status,
    )


def _actor(role: str = "ACCOUNT_HOLDER") -> User:
    return User(
        id=uuid.uuid4(),
        email="holder@example.com",
        full_name="Account Holder",
        password_hash="not-returned",
        role=role,
    )


@pytest.mark.parametrize(
    ("kind", "from_id", "to_id", "starting", "expected", "directions"),
    [
        (
            "DEPOSIT",
            None,
            2,
            {1: -100, 2: 100},
            {1: -125, 2: 125},
            [("DEBIT", 1, -125), ("CREDIT", 2, 125)],
        ),
        (
            "WITHDRAWAL",
            2,
            None,
            {1: -100, 2: 100},
            {1: -75, 2: 75},
            [("DEBIT", 2, 75), ("CREDIT", 1, -75)],
        ),
        (
            "TRANSFER",
            2,
            3,
            {2: 100, 3: 20},
            {2: 75, 3: 45},
            [("DEBIT", 2, 75), ("CREDIT", 3, 45)],
        ),
    ],
)
def test_post_movement_writes_balanced_ledger_and_audit(
    kind: str,
    from_id: int | None,
    to_id: int | None,
    starting: dict[int, int],
    expected: dict[int, int],
    directions: list[tuple[str, int, int]],
) -> None:
    actor = _actor()
    accounts = {
        account_id: _account(
            account_id,
            "ACC1001" if account_id == 1 else f"ACC{account_id:04d}",
            balance,
            is_system=account_id == 1,
        )
        for account_id, balance in starting.items()
    }
    db = FakeSession(
        list(accounts.values()),
        member_account_ids={from_id, to_id} - {None},
    )

    transaction = post_movement(
        db,  # type: ignore[arg-type]
        actor,
        kind,  # type: ignore[arg-type]
        from_id,
        to_id,
        25,
        idempotency_key=f"{kind.lower()}_key",
    )

    assert transaction.response_status == 201
    assert transaction.response_body["kind"] == kind
    assert {account_id: account.balance_paise for account_id, account in accounts.items()} == expected
    entries = [item for item in db.added if isinstance(item, LedgerEntry)]
    assert [
        (entry.direction, entry.account_id, entry.balance_after_paise)
        for entry in entries
    ] == directions
    for entry in entries:
        assert entry.created_at.tzinfo is not None
        assert entry.hash == _expected_entry_hash(entry)
    assert accounts[entries[0].account_id].last_entry_hash == entries[0].hash
    assert accounts[entries[1].account_id].last_entry_hash == entries[1].hash
    audit = next(item for item in db.added if isinstance(item, AuditLog))
    assert audit.action == kind
    assert db.committed
    assert not db.rolled_back
    assert "INSERT INTO idempotency_keys" in db.sql_log[0]
    statement = db.account_lock_statement
    assert statement is not None
    assert statement._for_update_arg is not None
    assert len(statement._order_by_clauses) == 1
    assert statement._order_by_clauses[0] == Account.id
    if kind == "TRANSFER":
        assert db.external_lookups == 0
        assert sorted(accounts) == [2, 3]
    else:
        assert db.external_lookups == 1
        assert sorted(accounts) == [1, 2]


def test_same_key_and_request_replays_response_without_moving_money() -> None:
    accounts = [
        _account(2, "ACC0002", 100),
        _account(3, "ACC0003", 20),
    ]
    db = FakeSession(accounts, member_account_ids={2})
    actor = _actor()

    original = post_movement(
        db, actor, "TRANSFER", 2, 3, 25, "replay_transfer_key"  # type: ignore[arg-type]
    )
    balances_after_first = [account.balance_paise for account in accounts]
    replay = post_movement(
        db, actor, "TRANSFER", 2, 3, 25, "replay_transfer_key"  # type: ignore[arg-type]
    )

    assert replay == original
    assert replay.response_status == 201
    assert [account.balance_paise for account in accounts] == balances_after_first
    assert len([item for item in db.added if isinstance(item, Transaction)]) == 1
    assert len([item for item in db.added if isinstance(item, LedgerEntry)]) == 2
    assert [
        item.action for item in db.added if isinstance(item, AuditLog)
    ] == ["TRANSFER", "IDEMPOTENT_REPLAY"]
    assert db.committed


def test_repeated_movement_chains_to_previous_account_hash() -> None:
    accounts = [
        _account(1, "ACC1001", -100, is_system=True),
        _account(2, "ACC0002", 100),
    ]
    db = FakeSession(accounts, member_account_ids={2})
    actor = _actor()

    post_movement(
        db, actor, "WITHDRAWAL", 2, None, 10, "withdrawal_chain_01"  # type: ignore[arg-type]
    )
    first_entry = next(
        item
        for item in db.added
        if isinstance(item, LedgerEntry) and item.account_id == 2
    )
    post_movement(
        db, actor, "WITHDRAWAL", 2, None, 10, "withdrawal_chain_02"  # type: ignore[arg-type]
    )
    account_entries = [
        item
        for item in db.added
        if isinstance(item, LedgerEntry) and item.account_id == 2
    ]

    assert account_entries[1].prev_hash == first_entry.hash
    assert account_entries[1].hash == _expected_entry_hash(account_entries[1])
    assert accounts[1].last_entry_hash == account_entries[1].hash
    assert verify_chain(
        FakeVerifySession(account_entries), 2
    ) is None  # type: ignore[arg-type]


def test_idempotency_keys_are_scoped_per_user() -> None:
    accounts = [
        _account(1, "ACC1001", -100, is_system=True),
        _account(2, "ACC0002", 100),
    ]
    db = FakeSession(accounts, role="ADMIN")
    first_user = _actor("ADMIN")
    second_user = _actor("ADMIN")

    first = post_movement(
        db, first_user, "DEPOSIT", None, 2, 25, "per_user_key_001"  # type: ignore[arg-type]
    )
    second = post_movement(
        db, second_user, "DEPOSIT", None, 2, 25, "per_user_key_001"  # type: ignore[arg-type]
    )

    assert first.response_body != second.response_body
    assert len(db.idempotency_rows) == 2
    assert accounts[1].balance_paise == 150


def test_reusing_key_for_different_request_is_refused_and_logged() -> None:
    accounts = [
        _account(1, "ACC1001", -100, is_system=True),
        _account(2, "ACC0002", 100),
    ]
    db = FakeSession(accounts, role="ADMIN")
    actor = _actor("ADMIN")

    post_movement(
        db, actor, "DEPOSIT", None, 2, 25, "request_mismatch_key"  # type: ignore[arg-type]
    )
    result = post_movement(
        db, actor, "DEPOSIT", None, 2, 30, "request_mismatch_key"  # type: ignore[arg-type]
    )

    assert result.response_status == 422
    assert result.response_body["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert accounts[1].balance_paise == 125
    assert len([item for item in db.added if isinstance(item, LedgerEntry)]) == 2
    assert len(db.refused_attempts) == 1
    assert db.refused_attempts[0]["reason_code"] == "IDEMPOTENCY_KEY_REUSED"
    assert db.committed


def test_refused_response_is_stored_and_replayed() -> None:
    db = FakeSession(
        [
            _account(1, "ACC1001", -10, is_system=True),
            _account(2, "ACC0002", 10),
        ],
        member_account_ids={2},
    )
    actor = _actor()

    refused = post_movement(
        db, actor, "WITHDRAWAL", 2, None, 25, "refused_replay_key"  # type: ignore[arg-type]
    )
    replay = post_movement(
        db, actor, "WITHDRAWAL", 2, None, 25, "refused_replay_key"  # type: ignore[arg-type]
    )

    assert refused.response_status == InsufficientFundsError.status_code
    assert replay == refused
    assert len(db.refused_attempts) == 1
    assert not any(isinstance(item, LedgerEntry) for item in db.added)
    assert [
        item.action for item in db.added if isinstance(item, AuditLog)
    ] == ["IDEMPOTENT_REPLAY"]


def test_replay_rechecks_current_database_authorization() -> None:
    db = FakeSession(
        [
            _account(1, "ACC1001", -100, is_system=True),
            _account(2, "ACC0002", 100),
        ],
        member_account_ids={2},
    )
    actor = _actor()

    original = post_movement(
        db, actor, "DEPOSIT", None, 2, 25, "authorization_replay_key"  # type: ignore[arg-type]
    )
    db.role = "AUDITOR"
    replay = post_movement(
        db, actor, "DEPOSIT", None, 2, 25, "authorization_replay_key"  # type: ignore[arg-type]
    )

    assert original.response_status == 201
    assert replay.response_status == ForbiddenMovementError.status_code
    assert replay.response_body["code"] == "FORBIDDEN"
    assert len([item for item in db.added if isinstance(item, LedgerEntry)]) == 2
    assert len(db.refused_attempts) == 1


def test_insufficient_funds_is_checked_after_account_rows_are_locked() -> None:
    actor = _actor()
    db = FakeSession(
        [
            _account(1, "ACC1001", -10, is_system=True),
            _account(2, "ACC0002", 10),
        ],
        member_account_ids={2},
    )

    result = post_movement(
        db, actor, "WITHDRAWAL", 2, None, 25, "shortfall_key"  # type: ignore[arg-type]
    )

    assert result.response_status == InsufficientFundsError.status_code
    assert db.committed
    assert db.account_lock_statement is not None
    assert db.account_lock_statement._for_update_arg is not None
    assert not any(isinstance(item, LedgerEntry) for item in db.added)
    assert len(db.refused_attempts) == 1


@pytest.mark.parametrize(
    "amount",
    [0, -1, True, 1.5, "100", None, 10_000_001, 2**63],
)
def test_invalid_amount_is_rejected(amount: object) -> None:
    db = FakeSession([])

    result = post_movement(
        db,  # type: ignore[arg-type]
        _actor("ADMIN"),
        "DEPOSIT",
        None,
        2,
        amount,  # type: ignore[arg-type]
        "invalid_amount_key",
    )

    assert result.response_status == InvalidAmountError.status_code
    assert db.committed
    assert len(db.refused_attempts) == 1
    assert db.account_lock_statement is None
    if amount == 2**63:
        assert db.refused_attempts[0]["amount_paise"] is None


def test_unexpected_error_rolls_back_idempotency_and_movement() -> None:
    db = FakeSession(
        [
            _account(1, "ACC1001", -100, is_system=True),
            _account(2, "ACC0002", 100),
        ],
        role="ADMIN",
    )
    execute = db.execute

    def fail_response_storage(
        statement: object,
        parameters: dict[str, object],
    ) -> FakeResult:
        if "UPDATE idempotency_keys" in str(statement):
            raise RuntimeError("response storage failed")
        return execute(statement, parameters)

    db.execute = fail_response_storage  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="response storage failed"):
        post_movement(
            db, _actor("ADMIN"), "DEPOSIT", None, 2, 25, "rollback_key"  # type: ignore[arg-type]
        )

    assert db.rolled_back
    assert not db.committed


def test_auditor_is_forbidden_from_moving_money() -> None:
    actor = _actor("AUDITOR")
    db = FakeSession(
        [
            _account(1, "ACC1001", -100, is_system=True),
            _account(2, "ACC0002", 100),
        ],
        role="AUDITOR",
    )

    result = post_movement(
        db, actor, "DEPOSIT", None, 2, 25, "auditor_key"  # type: ignore[arg-type]
    )

    assert result.response_status == ForbiddenMovementError.status_code
    assert db.committed
    assert len(db.refused_attempts) == 1


def test_admin_can_deposit_to_account_without_membership() -> None:
    db = FakeSession(
        [
            _account(1, "ACC1001", -100, is_system=True),
            _account(2, "ACC0002", 100),
        ],
        role="ADMIN",
    )

    post_movement(
        db, _actor("ADMIN"), "DEPOSIT", None, 2, 25, "admin_deposit_key"  # type: ignore[arg-type]
    )

    assert db.committed


@pytest.mark.parametrize(
    ("role", "kind", "from_id", "to_id", "accounts"),
    [
        (
            "ADMIN",
            "WITHDRAWAL",
            2,
            None,
            [
                _account(1, "ACC1001", -100, is_system=True),
                _account(2, "ACC0002", 100),
            ],
        ),
        (
            "ACCOUNT_HOLDER",
            "DEPOSIT",
            None,
            2,
            [
                _account(1, "ACC1001", -100, is_system=True),
                _account(2, "ACC0002", 100),
            ],
        ),
    ],
)
def test_membership_is_required_for_debits_and_holder_deposits(
    role: str,
    kind: str,
    from_id: int | None,
    to_id: int | None,
    accounts: list[Account],
) -> None:
    db = FakeSession(accounts, role=role)

    result = post_movement(
        db,
        _actor(role),
        kind,  # type: ignore[arg-type]
        from_id,
        to_id,
        25,
        "member_required_key",
    )

    assert result.response_status == ForbiddenMovementError.status_code
    assert db.committed
    assert len(db.refused_attempts) == 1


def test_nonmember_withdrawal_is_refused_before_account_row_lock() -> None:
    db = FakeSession(
        [
            _account(1, "ACC1001", -100, is_system=True),
            _account(2, "ACC0002", 100),
        ]
    )

    result = post_movement(
        db,
        _actor(),
        "WITHDRAWAL",
        2,
        None,
        25,
        "prelock_membership_key",
    )

    assert result.response_status == ForbiddenMovementError.status_code
    assert db.committed
    assert db.account_lock_statement is None
    assert len(db.membership_statements) == 1
    assert "FOR UPDATE" not in db.membership_statements[0]


def test_withdrawal_rechecks_membership_after_account_row_lock() -> None:
    db = FakeSession(
        [
            _account(1, "ACC1001", -100, is_system=True),
            _account(2, "ACC0002", 100),
        ],
        membership_results=[uuid.uuid4(), None],
    )

    result = post_movement(
        db,
        _actor(),
        "WITHDRAWAL",
        2,
        None,
        25,
        "membership_recheck_key",
    )

    assert result.response_status == ForbiddenMovementError.status_code
    assert db.committed
    assert db.account_lock_statement is not None
    assert len(db.membership_statements) == 2
    assert "FOR UPDATE" in db.membership_statements[1]


def test_transfer_source_membership_is_required_but_destination_membership_is_not() -> None:
    db = FakeSession(
        [_account(2, "ACC0002", 100), _account(3, "ACC0003", 20)],
        member_account_ids={2},
    )

    post_movement(
        db, _actor(), "TRANSFER", 2, 3, 25, "member_transfer_key"  # type: ignore[arg-type]
    )

    assert db.committed


def test_same_account_transfer_is_rejected() -> None:
    db = FakeSession([])

    result = post_movement(
        db, _actor(), "TRANSFER", 2, 2, 25, "same_account_key"  # type: ignore[arg-type]
    )

    assert result.response_status == ForbiddenMovementError.status_code
    assert db.committed
    assert db.external_lookups == 0


def test_missing_external_account_refuses_deposit() -> None:
    db = FakeSession([_account(2, "ACC0002", 100)])

    result = post_movement(
        db, _actor("ADMIN"), "DEPOSIT", None, 2, 25, "missing_external_key"  # type: ignore[arg-type]
    )

    assert result.response_status == AccountNotFoundError.status_code
    assert db.committed


def test_frozen_account_is_rejected_before_movement() -> None:
    db = FakeSession(
        [
            _account(1, "ACC1001", -100, is_system=True),
            _account(2, "ACC0002", 100, status="FROZEN"),
        ]
    )

    result = post_movement(
        db, _actor("ADMIN"), "DEPOSIT", None, 2, 25, "frozen_account_key"  # type: ignore[arg-type]
    )

    assert result.response_status == AccountFrozenError.status_code
    assert db.committed


def _verified_entry(
    *,
    entry_id: int,
    previous_hash: str | None,
    created_at: datetime,
    balance_after_paise: int,
) -> LedgerEntry:
    txn_id = uuid.uuid5(uuid.NAMESPACE_OID, f"txn-{entry_id}")
    initiated_by = uuid.uuid5(uuid.NAMESPACE_OID, "actor")
    entry = LedgerEntry(
        id=entry_id,
        txn_id=txn_id,
        account_id=7,
        direction="CREDIT",
        amount_paise=10,
        balance_after_paise=balance_after_paise,
        initiated_by=initiated_by,
        created_at=created_at,
        prev_hash=previous_hash,
        hash="",
    )
    entry.hash = _expected_entry_hash(entry)
    return entry


def test_verify_chain_accepts_valid_chain_and_detects_tampered_entry() -> None:
    timestamp = datetime(2026, 11, 8, 8, 0, tzinfo=UTC)
    first = _verified_entry(
        entry_id=11,
        previous_hash=None,
        created_at=timestamp,
        balance_after_paise=10,
    )
    second = _verified_entry(
        entry_id=15,
        previous_hash=first.hash,
        created_at=timestamp,
        balance_after_paise=20,
    )
    db = FakeVerifySession([second, first])

    assert verify_chain(db, 7) is None  # type: ignore[arg-type]

    second.balance_after_paise = 21
    assert verify_chain(db, 7) == second.id  # type: ignore[arg-type]


def test_verify_chain_detects_broken_previous_hash_link() -> None:
    timestamp = datetime(2026, 11, 8, 8, 0, tzinfo=UTC)
    first = _verified_entry(
        entry_id=11,
        previous_hash=None,
        created_at=timestamp,
        balance_after_paise=10,
    )
    second = _verified_entry(
        entry_id=15,
        previous_hash="wrong-previous-hash",
        created_at=timestamp,
        balance_after_paise=20,
    )

    assert verify_chain(FakeVerifySession([first, second]), 7) == second.id  # type: ignore[arg-type]


def test_verify_chain_accepts_empty_account_history() -> None:
    assert verify_chain(FakeVerifySession([]), 7) is None  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/deposits", {"account_id": 2, "amount_paise": 25}),
        ("/withdrawals", {"account_id": 2, "amount_paise": 25}),
        (
            "/transfers",
            {"from_account_id": 2, "to_account_id": 3, "amount_paise": 25},
        ),
    ],
)
@pytest.mark.parametrize(
    "key",
    [None, "short", "has spaces", "punctuation!", "a" * 129],
)
def test_money_endpoints_reject_missing_or_invalid_idempotency_key(
    path: str,
    body: dict[str, int],
    key: str | None,
) -> None:
    actor = _actor("ADMIN")
    app.dependency_overrides[current_user] = lambda: actor
    app.dependency_overrides[get_db] = lambda: object()
    headers = {} if key is None else {"Idempotency-Key": key}
    try:
        response = TestClient(app).post(path, json=body, headers=headers)
    finally:
        app.dependency_overrides.pop(current_user)
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 400


def test_auditor_is_refused_and_recorded_by_money_endpoint() -> None:
    auditor = _actor("AUDITOR")
    db = FakeSession(
        [
            _account(1, "ACC1001", -100, is_system=True),
            _account(2, "ACC0002", 100),
        ],
        role="AUDITOR",
    )
    app.dependency_overrides[current_user] = lambda: auditor
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).post(
            "/deposits",
            json={"account_id": 2, "amount_paise": 25},
            headers={"Idempotency-Key": "auditor_deposit_key"},
        )
    finally:
        app.dependency_overrides.pop(current_user)
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert len(db.refused_attempts) == 1
    assert db.committed
