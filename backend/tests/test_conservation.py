from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.ledger_entry import LedgerEntry
from app.models.transaction import Transaction
from app.models.user import User
from app.services.ledger import MovementKind, post_movement
from tests.factories import (
    DEFAULT_TEST_PASSWORD,
    assert_books_balance,
    fund_account,
    login_client,
    make_account,
    make_user,
)


def _account_balance_total(
    db_session: Session,
    *,
    system_accounts: bool,
) -> int:
    total = db_session.scalar(
        select(func.coalesce(func.sum(Account.balance_paise), 0)).where(
            Account.is_system.is_(system_accounts)
        )
    )
    return int(total)


def test_deposit_withdrawal_and_transfer_conserve_balances(db_session: Session) -> None:
    admin = make_user(db_session, role="ADMIN")
    holder = make_user(db_session)
    checking = make_account(db_session, holder, name="Checking")
    savings = make_account(
        db_session,
        holder,
        name="Savings",
        account_type="SAVINGS",
    )
    db_session.commit()

    non_system_before = _account_balance_total(
        db_session,
        system_accounts=False,
    )
    system_before = _account_balance_total(db_session, system_accounts=True)
    deposit_paise = 100_000
    withdrawal_paise = 15_000
    transfer_paise = 25_000

    fund_account(db_session, admin, checking, deposit_paise)
    withdrawal = post_movement(
        db_session,
        holder,
        "WITHDRAWAL",
        from_account_id=checking.id,
        to_account_id=None,
        amount_paise=withdrawal_paise,
        idempotency_key="conservation-withdrawal",
    )
    transfer = post_movement(
        db_session,
        holder,
        "TRANSFER",
        from_account_id=checking.id,
        to_account_id=savings.id,
        amount_paise=transfer_paise,
        idempotency_key="conservation-transfer",
    )

    assert withdrawal.response_status == 201
    assert transfer.response_status == 201
    assert (
        _account_balance_total(
            db_session,
            system_accounts=False,
        )
        - non_system_before
        == deposit_paise - withdrawal_paise
    )
    assert (
        db_session.scalar(
            select(func.coalesce(func.sum(Account.balance_paise), 0)).where(
                Account.id.in_([checking.id, savings.id])
            )
        )
        == deposit_paise - withdrawal_paise
    )
    assert _account_balance_total(db_session, system_accounts=True) - system_before == (
        withdrawal_paise - deposit_paise
    )
    assert (
        db_session.scalar(select(func.coalesce(func.sum(Account.balance_paise), 0)))
        == 0
    )
    assert_books_balance(db_session)


def test_random_concurrent_movements_preserve_the_books(
    db_session: Session,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    holders = [make_user(db_session) for _ in range(5)]
    accounts = [
        make_account(db_session, holder, name=f"Account {index}")
        for index, holder in enumerate(holders)
    ]
    db_session.commit()

    for account in accounts:
        fund_account(db_session, admin, account, 1_000_000)

    rng = random.Random(20261109)
    movement_kinds: tuple[MovementKind, ...] = (
        "DEPOSIT",
        "WITHDRAWAL",
        "TRANSFER",
    )
    kinds: list[MovementKind] = list(movement_kinds) + [
        rng.choice(movement_kinds) for _ in range(97)
    ]
    rng.shuffle(kinds)
    movements: list[tuple[MovementKind, int | None, int | None, int, UUID, str]] = []
    for index, kind in enumerate(kinds):
        source_index = rng.randrange(len(accounts))
        source = accounts[source_index]
        destination_index = rng.randrange(len(accounts) - 1)
        if destination_index >= source_index:
            destination_index += 1
        destination = accounts[destination_index]
        if kind == "DEPOSIT":
            from_account_id = None
            to_account_id = source.id
        elif kind == "WITHDRAWAL":
            from_account_id = source.id
            to_account_id = None
        else:
            from_account_id = source.id
            to_account_id = destination.id

        movements.append(
            (
                kind,
                from_account_id,
                to_account_id,
                rng.randint(1, 5_000),
                holders[source_index].id,
                f"random-conservation-{index:03d}",
            )
        )

    def run_movement(
        movement: tuple[MovementKind, int | None, int | None, int, UUID, str],
    ) -> int:
        kind, from_id, to_id, amount, actor_id, key = movement
        with SessionLocal() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            result = post_movement(
                session,
                actor,
                kind,
                from_account_id=from_id,
                to_account_id=to_id,
                amount_paise=amount,
                idempotency_key=key,
            )
            return result.response_status

    with ThreadPoolExecutor(max_workers=10) as executor:
        statuses = list(executor.map(run_movement, movements))

    assert len(statuses) == 100
    assert statuses == [201] * 100
    db_session.expire_all()
    assert_books_balance(db_session)

    holder_balances = db_session.scalars(
        select(Account.balance_paise)
        .join(AccountMember, AccountMember.account_id == Account.id)
        .where(
            Account.id.in_([account.id for account in accounts]),
            Account.is_system.is_(False),
        )
    ).all()
    assert len(holder_balances) == len(accounts)
    assert all(balance >= 0 for balance in holder_balances)


def test_unexpected_error_after_debit_insert_rolls_back_movement(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    holder = make_user(db_session)
    account = make_account(db_session, holder)
    db_session.commit()
    fund_account(db_session, admin, account, 50_000)

    account_balances_before = db_session.execute(
        select(
            Account.id,
            Account.balance_paise,
            Account.last_entry_hash,
        ).order_by(Account.id)
    ).all()
    ledger_before = db_session.execute(
        select(
            LedgerEntry.id,
            LedgerEntry.txn_id,
            LedgerEntry.account_id,
            LedgerEntry.direction,
            LedgerEntry.amount_paise,
            LedgerEntry.balance_after_paise,
            LedgerEntry.initiated_by,
            LedgerEntry.created_at,
            LedgerEntry.prev_hash,
            LedgerEntry.hash,
        ).order_by(LedgerEntry.id)
    ).all()
    transaction_ids_before = db_session.scalars(
        select(Transaction.id).order_by(Transaction.id)
    ).all()
    ledger_count_before = len(ledger_before)

    def add_debit_then_fail(instances: list[object]) -> None:
        debit_entry = instances[0]
        assert isinstance(debit_entry, LedgerEntry)
        assert debit_entry.direction == "DEBIT"
        db_session.add(debit_entry)
        db_session.flush()
        assert (
            db_session.scalar(select(func.count()).select_from(LedgerEntry))
            == ledger_count_before + 1
        )
        raise RuntimeError("simulated failure after debit insert")

    monkeypatch.setattr(db_session, "add_all", add_debit_then_fail)
    with pytest.raises(RuntimeError, match="after debit insert"):
        post_movement(
            db_session,
            holder,
            "WITHDRAWAL",
            from_account_id=account.id,
            to_account_id=None,
            amount_paise=10_000,
            idempotency_key="conservation-rollback",
        )

    db_session.expire_all()
    account_balances_after = db_session.execute(
        select(
            Account.id,
            Account.balance_paise,
            Account.last_entry_hash,
        ).order_by(Account.id)
    ).all()
    ledger_after = db_session.execute(
        select(
            LedgerEntry.id,
            LedgerEntry.txn_id,
            LedgerEntry.account_id,
            LedgerEntry.direction,
            LedgerEntry.amount_paise,
            LedgerEntry.balance_after_paise,
            LedgerEntry.initiated_by,
            LedgerEntry.created_at,
            LedgerEntry.prev_hash,
            LedgerEntry.hash,
        ).order_by(LedgerEntry.id)
    ).all()
    transaction_ids_after = db_session.scalars(
        select(Transaction.id).order_by(Transaction.id)
    ).all()
    assert account_balances_after == account_balances_before
    assert ledger_after == ledger_before
    assert transaction_ids_after == transaction_ids_before
    assert_books_balance(db_session)


@pytest.mark.asyncio
async def test_admin_reconcile_endpoint_passes(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    db_session.commit()
    client = await login_client(
        uvicorn_server,
        admin,
        password=DEFAULT_TEST_PASSWORD,
    )
    try:
        response = await client.get("/admin/reconcile")
    finally:
        await client.aclose()

    assert response.status_code == 200
    report = response.json()
    assert report["passed"] is True
    assert report["accounts_sum_to_zero"] is True
    assert report["accounts_match_ledger"] is True
    assert report["non_system_accounts_nonnegative"] is True
    assert report["transactions_balanced"] is True
