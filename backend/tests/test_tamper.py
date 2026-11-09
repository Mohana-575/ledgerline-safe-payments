from __future__ import annotations

import uuid

import pytest
from fastapi import Request
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

import app.api.routes.admin as admin_routes
from app.core.config import get_settings
from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.ledger_entry import LedgerEntry
from app.models.refused_attempt import RefusedAttempt
from app.models.transaction import Transaction
from app.models.user import User
from app.services.ledger import post_movement
from tests.factories import fund_account, make_account, make_user


def _assert_database_error(
    error: DBAPIError,
    *,
    sqlstate: str,
    message: str,
    constraint_name: str | None = None,
) -> None:
    original = error.orig
    assert getattr(original, "sqlstate", None) == sqlstate, str(original)
    assert message.lower() in str(original).lower()
    if constraint_name is not None:
        diagnostic = getattr(original, "diag", None)
        assert diagnostic is not None
        assert diagnostic.constraint_name == constraint_name


def _append_only_rows(
    db_session: Session,
) -> dict[str, int | uuid.UUID]:
    admin = make_user(db_session, role="ADMIN")
    holder = make_user(db_session)
    account = make_account(db_session, holder)
    db_session.commit()
    fund_account(db_session, admin, account, 5_000)
    refused = post_movement(
        db_session,
        holder,
        "WITHDRAWAL",
        from_account_id=account.id,
        to_account_id=None,
        amount_paise=6_000,
        idempotency_key="tamper-refused-attempt",
    )
    assert refused.response_status == 409

    return {
        "transactions": db_session.scalar(select(Transaction.id)),
        "ledger_entries": db_session.scalar(select(LedgerEntry.id)),
        "refused_attempts": db_session.scalar(select(RefusedAttempt.id)),
        "audit_logs": db_session.scalar(select(AuditLog.id)),
    }


def test_append_only_mutations_fail_on_direct_database_connections(
    db_session: Session,
) -> None:
    row_ids = _append_only_rows(db_session)
    db_session.commit()
    statements = {
        "transactions": (
            "UPDATE transactions SET type = type WHERE id = :id",
            "DELETE FROM transactions WHERE id = :id",
        ),
        "ledger_entries": (
            "UPDATE ledger_entries SET amount_paise = amount_paise WHERE id = :id",
            "DELETE FROM ledger_entries WHERE id = :id",
        ),
        "refused_attempts": (
            "UPDATE refused_attempts SET reason_code = reason_code WHERE id = :id",
            "DELETE FROM refused_attempts WHERE id = :id",
        ),
        "audit_logs": (
            "UPDATE audit_logs SET action = action WHERE id = :id",
            "DELETE FROM audit_logs WHERE id = :id",
        ),
    }
    engine = create_engine(get_settings().DATABASE_URL, pool_pre_ping=True)
    try:
        for table, (update_sql, delete_sql) in statements.items():
            row_id = row_ids[table]
            truncate_sql = (
                f"TRUNCATE TABLE {table} CASCADE"
                if table == "transactions"
                else f"TRUNCATE TABLE {table}"
            )
            for operation, statement in (
                ("UPDATE", update_sql),
                ("DELETE", delete_sql),
                ("TRUNCATE", truncate_sql),
            ):
                with (
                    pytest.raises(DBAPIError) as error,
                    engine.begin() as connection,
                ):
                    if operation == "TRUNCATE":
                        connection.execute(text(statement))
                    else:
                        connection.execute(text(statement), {"id": row_id})
                _assert_database_error(
                    error.value,
                    sqlstate="55000",
                    message=f"table {table} is append-only; {operation}",
                )
    finally:
        engine.dispose()


def _entry_context(db_session: Session) -> tuple[User, Account]:
    user = make_user(db_session)
    account = make_account(db_session, user)
    db_session.commit()
    return user, account


def test_unbalanced_ledger_transaction_fails_at_commit(
    db_session: Session,
) -> None:
    user, account = _entry_context(db_session)
    transaction = Transaction(type="TRANSFER", initiated_by=user.id)
    db_session.add(transaction)
    db_session.flush()
    db_session.add_all(
        [
            LedgerEntry(
                txn_id=transaction.id,
                account_id=account.id,
                direction="DEBIT",
                amount_paise=100,
                balance_after_paise=0,
                initiated_by=user.id,
                hash="unbalanced-debit",
            ),
            LedgerEntry(
                txn_id=transaction.id,
                account_id=account.id,
                direction="CREDIT",
                amount_paise=99,
                balance_after_paise=99,
                initiated_by=user.id,
                hash="unbalanced-credit",
            ),
        ]
    )

    try:
        with pytest.raises(IntegrityError) as error:
            db_session.commit()
        _assert_database_error(
            error.value,
            sqlstate="23514",
            message="is unbalanced",
        )
    finally:
        db_session.rollback()


@pytest.mark.parametrize("amount_paise", [0, -1])
def test_nonpositive_ledger_amount_fails_check_constraint(
    db_session: Session,
    amount_paise: int,
) -> None:
    user, account = _entry_context(db_session)
    transaction = Transaction(type="DEPOSIT", initiated_by=user.id)
    db_session.add(transaction)
    db_session.flush()
    db_session.add(
        LedgerEntry(
            txn_id=transaction.id,
            account_id=account.id,
            direction="CREDIT",
            amount_paise=amount_paise,
            balance_after_paise=amount_paise,
            initiated_by=user.id,
            hash="invalid-amount",
        )
    )

    try:
        with pytest.raises(IntegrityError) as error:
            db_session.commit()
        _assert_database_error(
            error.value,
            sqlstate="23514",
            message="violates check constraint",
            constraint_name="ck_ledger_entries_amount_positive",
        )
    finally:
        db_session.rollback()


def test_normal_account_cannot_be_set_to_negative_balance(
    db_session: Session,
) -> None:
    user = make_user(db_session)
    account = make_account(db_session, user)
    db_session.commit()
    account.balance_paise = -1

    try:
        with pytest.raises(IntegrityError) as error:
            db_session.commit()
        _assert_database_error(
            error.value,
            sqlstate="23514",
            message="violates check constraint",
            constraint_name="ck_accounts_non_system_balance_nonnegative",
        )
    finally:
        db_session.rollback()


def test_ledger_hash_verification_detects_owner_tampering_and_rolls_back(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    holder = make_user(db_session)
    account = make_account(db_session, holder)
    db_session.commit()
    fund_account(db_session, admin, account, 5_000)

    entry = db_session.scalar(
        select(LedgerEntry)
        .where(LedgerEntry.account_id == account.id)
        .order_by(LedgerEntry.id)
    )
    assert entry is not None
    entry_id = entry.id
    original_amount = entry.amount_paise
    current_user = db_session.scalar(text("SELECT current_user"))
    database_owner = db_session.scalar(
        text(
            "SELECT pg_get_userbyid(datdba) "
            "FROM pg_database WHERE datname = current_database()"
        )
    )
    assert current_user == database_owner

    try:
        db_session.execute(
            text(
                "ALTER TABLE ledger_entries "
                "DISABLE TRIGGER ledger_entries_reject_update_delete"
            )
        )
        db_session.execute(
            text(
                "UPDATE ledger_entries SET amount_paise = amount_paise + 1 "
                "WHERE id = :entry_id"
            ),
            {"entry_id": entry_id},
        )
        db_session.expire_all()
        # Keep the verification request's audit side effect inside this rollback.
        monkeypatch.setattr(
            admin_routes,
            "_record_run",
            lambda *_args, **_kwargs: None,
        )
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/admin/verify-ledger",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "server": ("127.0.0.1", 80),
                "scheme": "http",
                "query_string": b"",
                "root_path": "",
            }
        )
        report = admin_routes.get_ledger_verification(request, db_session, admin)
        account_report = next(
            item for item in report.accounts if item.account_id == account.id
        )
        assert account_report.passed is False
        assert account_report.first_broken_entry_id == entry_id
    finally:
        db_session.rollback()

    restored_entry = db_session.get(LedgerEntry, entry_id)
    assert restored_entry is not None
    assert restored_entry.amount_paise == original_amount
    restored_report = admin_routes.get_ledger_verification(
        request,
        db_session,
        admin,
    )
    restored_account_report = next(
        item for item in restored_report.accounts if item.account_id == account.id
    )
    assert restored_account_report.passed is True
    assert restored_account_report.first_broken_entry_id is None
