import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.audit_log import AuditLog
from app.models.ledger_entry import LedgerEntry
from app.models.transaction import Transaction
from app.models.user import User
from app.services.ledger_errors import (
    AccountFrozenError,
    AccountNotFoundError,
    ForbiddenMovementError,
    IdempotencyKeyReusedError,
    InsufficientFundsError,
    InvalidAmountError,
    LedgerError,
)

MovementKind = Literal["DEPOSIT", "WITHDRAWAL", "TRANSFER"]
EXTERNAL_ACCOUNT_NUMBER = "ACC1000"


@dataclass(frozen=True)
class MovementResult:
    response_status: int
    response_body: dict[str, object]


@dataclass(frozen=True)
class AccountBalanceMismatch:
    account_id: int
    account_number: str
    balance_paise: int
    ledger_balance_paise: int


@dataclass(frozen=True)
class NegativeAccountBalance:
    account_id: int
    account_number: str
    balance_paise: int


@dataclass(frozen=True)
class TransactionBalanceMismatch:
    transaction_id: uuid.UUID
    debits_paise: int
    credits_paise: int


@dataclass(frozen=True)
class ReconciliationResult:
    total_balance_paise: int
    account_mismatches: tuple[AccountBalanceMismatch, ...]
    negative_accounts: tuple[NegativeAccountBalance, ...]
    transaction_mismatches: tuple[TransactionBalanceMismatch, ...]


def sum_account_balances(
    db_session: Session,
    account_ids: list[int],
) -> int:
    if not account_ids:
        return 0
    total = db_session.scalar(
        select(func.coalesce(func.sum(Account.balance_paise), 0)).where(
            Account.id.in_(account_ids)
        )
    )
    return int(total)


def reconcile_ledger(db_session: Session) -> ReconciliationResult:
    total_balance = db_session.scalar(
        select(func.coalesce(func.sum(Account.balance_paise), 0))
    )
    ledger_net = case(
        (LedgerEntry.direction == "CREDIT", LedgerEntry.amount_paise),
        (LedgerEntry.direction == "DEBIT", -LedgerEntry.amount_paise),
        else_=0,
    )
    account_rows = db_session.execute(
        select(
            Account.id,
            Account.account_number,
            Account.balance_paise,
            func.coalesce(func.sum(ledger_net), 0).label("ledger_balance_paise"),
        )
        .outerjoin(LedgerEntry, LedgerEntry.account_id == Account.id)
        .group_by(Account.id)
        .order_by(Account.id)
    ).all()
    account_mismatches = tuple(
        AccountBalanceMismatch(
            account_id=account_id,
            account_number=account_number,
            balance_paise=int(balance_paise),
            ledger_balance_paise=int(ledger_balance_paise),
        )
        for account_id, account_number, balance_paise, ledger_balance_paise in account_rows
        if int(balance_paise) != int(ledger_balance_paise)
    )
    negative_rows = db_session.execute(
        select(Account.id, Account.account_number, Account.balance_paise)
        .where(Account.is_system.is_(False), Account.balance_paise < 0)
        .order_by(Account.id)
    ).all()
    negative_accounts = tuple(
        NegativeAccountBalance(
            account_id=account_id,
            account_number=account_number,
            balance_paise=int(balance_paise),
        )
        for account_id, account_number, balance_paise in negative_rows
    )
    debit_total = func.coalesce(
        func.sum(
            case(
                (LedgerEntry.direction == "DEBIT", LedgerEntry.amount_paise),
                else_=0,
            )
        ),
        0,
    )
    credit_total = func.coalesce(
        func.sum(
            case(
                (LedgerEntry.direction == "CREDIT", LedgerEntry.amount_paise),
                else_=0,
            )
        ),
        0,
    )
    transaction_rows = db_session.execute(
        select(
            Transaction.id,
            debit_total.label("debits_paise"),
            credit_total.label("credits_paise"),
        )
        .outerjoin(LedgerEntry, LedgerEntry.txn_id == Transaction.id)
        .group_by(Transaction.id)
        .order_by(Transaction.id)
    ).all()
    transaction_mismatches = tuple(
        TransactionBalanceMismatch(
            transaction_id=transaction_id,
            debits_paise=int(debits_paise),
            credits_paise=int(credits_paise),
        )
        for transaction_id, debits_paise, credits_paise in transaction_rows
        if int(debits_paise) != int(credits_paise)
    )
    return ReconciliationResult(
        total_balance_paise=int(total_balance),
        account_mismatches=account_mismatches,
        negative_accounts=negative_accounts,
        transaction_mismatches=transaction_mismatches,
    )


def _request_hash(
    kind: MovementKind,
    from_account_id: int | None,
    to_account_id: int | None,
    amount_paise: int,
) -> str:
    canonical_request = json.dumps(
        (kind, from_account_id, to_account_id, amount_paise),
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()


def _idempotency_inserted(
    db_session: Session,
    *,
    user_id: uuid.UUID,
    key: str,
    request_hash: str,
) -> bool:
    result = db_session.execute(
        text(
            """
            INSERT INTO idempotency_keys (user_id, key, request_hash, status)
            VALUES (:user_id, :key, :request_hash, 'PENDING')
            ON CONFLICT (user_id, key) DO NOTHING
            RETURNING key
            """
        ),
        {"user_id": user_id, "key": key, "request_hash": request_hash},
    )
    return result.first() is not None


def _store_idempotency_response(
    db_session: Session,
    *,
    user_id: uuid.UUID,
    key: str,
    status_value: str,
    result: MovementResult,
) -> None:
    updated = db_session.execute(
        text(
            """
            UPDATE idempotency_keys
            SET status = :status,
                response_status = :response_status,
                response_body = CAST(:response_body AS JSONB)
            WHERE user_id = :user_id AND key = :key
            """
        ),
        {
            "user_id": user_id,
            "key": key,
            "status": status_value,
            "response_status": result.response_status,
            "response_body": json.dumps(result.response_body, separators=(",", ":")),
        },
    )
    if updated.rowcount != 1:
        raise RuntimeError("Idempotency row disappeared before response storage")


def _log_refused_attempt(
    db_session: Session,
    *,
    actor_id: uuid.UUID,
    account_id: int | None,
    kind: MovementKind,
    amount_paise: int,
    key: str,
    reason_code: str,
) -> None:
    stored_account_id = (
        account_id
        if type(account_id) is int and 0 < account_id < 2**63
        else None
    )
    if stored_account_id is not None:
        stored_account_id = db_session.scalar(
            select(Account.id).where(Account.id == stored_account_id)
        )
    stored_amount = (
        amount_paise
        if type(amount_paise) is int and -(2**63) <= amount_paise < 2**63
        else None
    )
    db_session.execute(
        text(
            """
            INSERT INTO refused_attempts (
                user_id, account_id, type, amount_paise, reason_code, idempotency_key
            )
            VALUES (:user_id, :account_id, :kind, :amount_paise, :reason_code, :key)
            """
        ),
        {
            "user_id": actor_id,
            "account_id": stored_account_id,
            "kind": kind,
            "amount_paise": stored_amount,
            "reason_code": reason_code,
            "key": key,
        },
    )


def _attempt_account_id(
    kind: MovementKind,
    from_account_id: int | None,
    to_account_id: int | None,
) -> int | None:
    return to_account_id if kind == "DEPOSIT" else from_account_id


def _movement_response(transaction: Transaction) -> MovementResult:
    return MovementResult(
        response_status=201,
        response_body={
            "transaction_id": str(transaction.id),
            "kind": transaction.type,
        },
    )


def _error_response(error: LedgerError) -> MovementResult:
    return MovementResult(
        response_status=error.status_code,
        response_body={"code": error.code.value, "message": error.message},
    )


def _replay_authorization_error(
    db_session: Session,
    actor_id: uuid.UUID,
) -> LedgerError | None:
    current_role = db_session.scalar(
        select(User.role).where(User.id == actor_id).with_for_update()
    )
    if current_role not in {"ADMIN", "ACCOUNT_HOLDER"}:
        return ForbiddenMovementError("Role is not allowed to move money")
    return None


def _perform_movement(
    db_session: Session,
    actor: User,
    kind: MovementKind,
    from_account_id: int | None,
    to_account_id: int | None,
    amount_paise: int,
) -> Transaction:
    _validate_amount(amount_paise)
    if kind == "TRANSFER" and from_account_id == to_account_id:
        raise ForbiddenMovementError("Transfer source and destination must differ")
    if kind == "DEPOSIT" and to_account_id is None:
        raise AccountNotFoundError("Deposit destination account not found")
    if kind == "WITHDRAWAL" and from_account_id is None:
        raise AccountNotFoundError("Withdrawal source account not found")
    if kind == "TRANSFER" and (
        from_account_id is None or to_account_id is None
    ):
        raise AccountNotFoundError("Transfer source or destination account not found")

    external_account_id: int | None = None
    if kind in {"DEPOSIT", "WITHDRAWAL"}:
        external_account_id = db_session.scalar(
            select(Account.id).where(
                Account.account_number == EXTERNAL_ACCOUNT_NUMBER,
                Account.is_system.is_(True),
            )
        )
        if external_account_id is None:
            raise AccountNotFoundError("External account not found")

    if kind == "DEPOSIT":
        debit_account_id = external_account_id
        credit_account_id = to_account_id
    elif kind == "WITHDRAWAL":
        debit_account_id = from_account_id
        credit_account_id = external_account_id
    else:
        debit_account_id = from_account_id
        credit_account_id = to_account_id

    if debit_account_id == credit_account_id:
        raise ForbiddenMovementError("Movement accounts must differ")

    account_ids = sorted({debit_account_id, credit_account_id})
    locked_accounts = db_session.scalars(
        select(Account)
        .where(Account.id.in_(account_ids))
        .order_by(Account.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    accounts = {account.id: account for account in locked_accounts}
    if len(accounts) != len(account_ids):
        raise AccountNotFoundError("Movement account not found")

    for account in locked_accounts:
        if account.status != "ACTIVE":
            raise AccountFrozenError("Account is not active")

    current_role = db_session.scalar(
        select(User.role).where(User.id == actor.id).with_for_update()
    )
    if current_role not in {"ADMIN", "ACCOUNT_HOLDER"}:
        raise ForbiddenMovementError("Role is not allowed to move money")

    if kind == "DEPOSIT" and current_role == "ADMIN":
        pass
    elif kind == "DEPOSIT":
        _assert_member(
            db_session,
            user_id=actor.id,
            account_id=to_account_id,
        )
    else:
        _assert_member(
            db_session,
            user_id=actor.id,
            account_id=from_account_id,
        )

    debit_account = accounts[debit_account_id]
    credit_account = accounts[credit_account_id]
    if kind != "DEPOSIT" and debit_account.balance_paise < amount_paise:
        raise InsufficientFundsError("Insufficient funds")

    txn = Transaction(type=kind, initiated_by=actor.id)
    db_session.add(txn)
    db_session.flush()

    debit_balance = debit_account.balance_paise - amount_paise
    credit_balance = credit_account.balance_paise + amount_paise
    debit_created_at = datetime.now(UTC)
    credit_created_at = datetime.now(UTC)
    entries = (
        LedgerEntry(
            txn_id=txn.id,
            account_id=debit_account.id,
            direction="DEBIT",
            amount_paise=amount_paise,
            balance_after_paise=debit_balance,
            initiated_by=actor.id,
            created_at=debit_created_at,
            prev_hash=debit_account.last_entry_hash,
            hash=_entry_hash(
                txn_id=txn.id,
                account_id=debit_account.id,
                direction="DEBIT",
                amount_paise=amount_paise,
                balance_after_paise=debit_balance,
                initiated_by=actor.id,
                prev_hash=debit_account.last_entry_hash,
                created_at=debit_created_at,
            ),
        ),
        LedgerEntry(
            txn_id=txn.id,
            account_id=credit_account.id,
            direction="CREDIT",
            amount_paise=amount_paise,
            balance_after_paise=credit_balance,
            initiated_by=actor.id,
            created_at=credit_created_at,
            prev_hash=credit_account.last_entry_hash,
            hash=_entry_hash(
                txn_id=txn.id,
                account_id=credit_account.id,
                direction="CREDIT",
                amount_paise=amount_paise,
                balance_after_paise=credit_balance,
                initiated_by=actor.id,
                prev_hash=credit_account.last_entry_hash,
                created_at=credit_created_at,
            ),
        ),
    )
    db_session.add_all(entries)
    db_session.flush()
    debit_account.balance_paise = debit_balance
    debit_account.last_entry_hash = entries[0].hash
    credit_account.balance_paise = credit_balance
    credit_account.last_entry_hash = entries[1].hash
    db_session.add(
        AuditLog(
            user_id=actor.id,
            action=kind,
            details={
                "transaction_id": str(txn.id),
                "from_account_id": str(from_account_id),
                "to_account_id": str(to_account_id),
                "amount_paise": str(amount_paise),
            },
        )
    )
    return txn


def _entry_hash(
    *,
    txn_id: uuid.UUID,
    account_id: int,
    direction: str,
    amount_paise: int,
    balance_after_paise: int,
    initiated_by: uuid.UUID,
    prev_hash: str | None,
    created_at: datetime,
) -> str:
    payload = json.dumps(
        {
            "prev_hash": prev_hash,
            "txn_id": str(txn_id),
            "account_id": account_id,
            "direction": direction,
            "amount_paise": amount_paise,
            "balance_after_paise": balance_after_paise,
            "created_at": created_at.astimezone(UTC).isoformat(),
            "initiated_by": str(initiated_by),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _assert_member(
    db_session: Session,
    *,
    user_id: uuid.UUID,
    account_id: int,
) -> None:
    membership = db_session.scalar(
        select(AccountMember.user_id)
        .where(
            AccountMember.user_id == user_id,
            AccountMember.account_id == account_id,
        )
        .with_for_update()
    )
    if membership is None:
        raise ForbiddenMovementError("Account membership is required")


def _validate_amount(amount_paise: int) -> None:
    if type(amount_paise) is not int or not 0 < amount_paise <= (
        get_settings().MAX_AMOUNT_PAISE
    ):
        raise InvalidAmountError(
            f"amount_paise must be a positive integer no greater than "
            f"{get_settings().MAX_AMOUNT_PAISE}"
        )


def post_movement(
    db_session: Session,
    actor: User,
    kind: MovementKind,
    from_account_id: int | None,
    to_account_id: int | None,
    amount_paise: int,
    idempotency_key: str,
) -> MovementResult:
    if not db_session.in_transaction():
        db_session.begin()

    try:
        request_hash = _request_hash(
            kind,
            from_account_id,
            to_account_id,
            amount_paise,
        )
        is_first_request = _idempotency_inserted(
            db_session,
            user_id=actor.id,
            key=idempotency_key,
            request_hash=request_hash,
        )

        if not is_first_request:
            existing = db_session.execute(
                text(
                    """
                    SELECT request_hash, status, response_status, response_body
                    FROM idempotency_keys
                    WHERE user_id = :user_id AND key = :key
                    """
                ),
                {"user_id": actor.id, "key": idempotency_key},
            ).mappings().one()
            if existing["request_hash"] != request_hash:
                error = IdempotencyKeyReusedError(
                    "Idempotency-Key was already used for a different request"
                )
                _log_refused_attempt(
                    db_session,
                    actor_id=actor.id,
                    account_id=_attempt_account_id(
                        kind,
                        from_account_id,
                        to_account_id,
                    ),
                    kind=kind,
                    amount_paise=amount_paise,
                    key=idempotency_key,
                    reason_code=error.code.value,
                )
                db_session.commit()
                return _error_response(error)

            if (
                existing["status"] == "PENDING"
                or existing["response_status"] is None
                or existing["response_body"] is None
            ):
                raise RuntimeError("Committed idempotency row has no response")
            authorization_error = _replay_authorization_error(
                db_session,
                actor.id,
            )
            if authorization_error is not None:
                _log_refused_attempt(
                    db_session,
                    actor_id=actor.id,
                    account_id=_attempt_account_id(
                        kind,
                        from_account_id,
                        to_account_id,
                    ),
                    kind=kind,
                    amount_paise=amount_paise,
                    key=idempotency_key,
                    reason_code=authorization_error.code.value,
                )
                db_session.commit()
                return _error_response(authorization_error)

            db_session.add(
                AuditLog(
                    user_id=actor.id,
                    action="IDEMPOTENT_REPLAY",
                    details={
                        "idempotency_key": idempotency_key,
                        "response_status": str(existing["response_status"]),
                    },
                )
            )
            db_session.commit()
            return MovementResult(
                response_status=existing["response_status"],
                response_body=existing["response_body"],
            )

        try:
            transaction = _perform_movement(
                db_session,
                actor,
                kind,
                from_account_id,
                to_account_id,
                amount_paise,
            )
        except LedgerError as error:
            result = _error_response(error)
            _log_refused_attempt(
                db_session,
                actor_id=actor.id,
                account_id=_attempt_account_id(
                    kind,
                    from_account_id,
                    to_account_id,
                ),
                kind=kind,
                amount_paise=amount_paise,
                key=idempotency_key,
                reason_code=error.code.value,
            )
            _store_idempotency_response(
                db_session,
                user_id=actor.id,
                key=idempotency_key,
                status_value="REFUSED",
                result=result,
            )
            db_session.commit()
            return result

        result = _movement_response(transaction)
        _store_idempotency_response(
            db_session,
            user_id=actor.id,
            key=idempotency_key,
            status_value="SUCCEEDED",
            result=result,
        )
        db_session.commit()
        return result
    except Exception:
        db_session.rollback()
        raise
