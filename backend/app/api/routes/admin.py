import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, require_roles
from app.db.session import get_db
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.audit_log import AuditLog
from app.models.ledger_entry import LedgerEntry
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.admin import (
    AdminUserResponse,
    AccountBalanceMismatchResponse,
    DashboardAccount,
    DashboardResponse,
    DashboardTransaction,
    LedgerChainStatus,
    LedgerVerificationResponse,
    NegativeAccountBalanceResponse,
    ReconciliationResponse,
    TransactionBalanceMismatchResponse,
)
from app.services.ledger import reconcile_ledger, sum_account_balances
from app.services.verify import verify_chain

router = APIRouter(tags=["admin"])


@router.get("/admin/users", response_model=list[AdminUserResponse])
def list_admin_users(
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[User, Depends(require_roles("ADMIN"))],
) -> list[User]:
    return list(
        db.scalars(select(User).order_by(User.full_name, User.id)).all()
    )


@router.get("/users", response_model=list[AdminUserResponse])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[User, Depends(require_roles("ADMIN", "AUDITOR"))],
) -> list[User]:
    return list(
        db.scalars(select(User).order_by(User.full_name, User.id)).all()
    )


def _record_run(
    db: Session,
    request: Request,
    *,
    actor_id: uuid.UUID,
    action: str,
    details: dict[str, str],
) -> None:
    db.add(
        AuditLog(
            user_id=actor_id,
            action=action,
            details=details,
            ip=request.client.host if request.client is not None else None,
        )
    )
    db.commit()


@router.get("/admin/reconcile", response_model=ReconciliationResponse)
def get_reconciliation(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("ADMIN", "AUDITOR"))],
) -> ReconciliationResponse:
    result = reconcile_ledger(db)
    sum_balanced = result.total_balance_paise == 0
    accounts_match = not result.account_mismatches
    accounts_nonnegative = not result.negative_accounts
    transactions_balanced = not result.transaction_mismatches
    passed = (
        sum_balanced
        and accounts_match
        and accounts_nonnegative
        and transactions_balanced
    )
    _record_run(
        db,
        request,
        actor_id=actor.id,
        action="RECONCILIATION_RUN",
        details={
            "passed": str(passed).lower(),
            "account_balance_sum_paise": str(result.total_balance_paise),
            "account_mismatches": str(len(result.account_mismatches)),
            "negative_accounts": str(len(result.negative_accounts)),
            "transaction_mismatches": str(len(result.transaction_mismatches)),
        },
    )
    return ReconciliationResponse(
        passed=passed,
        account_balance_sum_paise=result.total_balance_paise,
        accounts_sum_to_zero=sum_balanced,
        accounts_match_ledger=accounts_match,
        account_mismatches=[
            AccountBalanceMismatchResponse(
                account_id=mismatch.account_id,
                account_number=mismatch.account_number,
                balance_paise=mismatch.balance_paise,
                ledger_balance_paise=mismatch.ledger_balance_paise,
            )
            for mismatch in result.account_mismatches
        ],
        non_system_accounts_nonnegative=accounts_nonnegative,
        negative_accounts=[
            NegativeAccountBalanceResponse(
                account_id=account.account_id,
                account_number=account.account_number,
                balance_paise=account.balance_paise,
            )
            for account in result.negative_accounts
        ],
        transactions_balanced=transactions_balanced,
        transaction_mismatches=[
            TransactionBalanceMismatchResponse(
                transaction_id=mismatch.transaction_id,
                debits_paise=mismatch.debits_paise,
                credits_paise=mismatch.credits_paise,
            )
            for mismatch in result.transaction_mismatches
        ],
    )


@router.get(
    "/admin/verify-ledger",
    response_model=LedgerVerificationResponse,
)
def get_ledger_verification(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("ADMIN", "AUDITOR"))],
) -> LedgerVerificationResponse:
    account_ids = db.scalars(select(Account.id).order_by(Account.id)).all()
    accounts: list[LedgerChainStatus] = []
    for account_id in account_ids:
        broken_entry_id = verify_chain(db, account_id)
        accounts.append(
            LedgerChainStatus(
                account_id=account_id,
                passed=broken_entry_id is None,
                first_broken_entry_id=broken_entry_id,
            )
        )
    passed = all(account.passed for account in accounts)
    failed_count = sum(not account.passed for account in accounts)
    _record_run(
        db,
        request,
        actor_id=actor.id,
        action="LEDGER_VERIFICATION_RUN",
        details={
            "passed": str(passed).lower(),
            "accounts_checked": str(len(accounts)),
            "failed_accounts": str(failed_count),
        },
    )
    return LedgerVerificationResponse(
        passed=passed,
        accounts_checked=len(accounts),
        accounts=accounts,
    )


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> DashboardResponse:
    account_ids = list(
        db.scalars(
            select(AccountMember.account_id).where(AccountMember.user_id == user.id)
        ).all()
    )
    accounts = (
        db.scalars(
            select(Account)
            .where(Account.id.in_(account_ids))
            .order_by(Account.id)
        ).all()
        if account_ids
        else []
    )
    dashboard_accounts = [
        DashboardAccount(
            id=account.id,
            account_number=account.account_number,
            name=account.name,
            type=account.type,
            balance_paise=account.balance_paise,
            status=account.status,
        )
        for account in accounts
    ]
    transaction_count = 0
    recent_transactions: list[DashboardTransaction] = []
    if account_ids:
        cutoff = datetime.now(UTC) - timedelta(days=30)
        transaction_count = int(
            db.scalar(
                select(func.count(func.distinct(Transaction.id)))
                .join(LedgerEntry, LedgerEntry.txn_id == Transaction.id)
                .where(
                    LedgerEntry.account_id.in_(account_ids),
                    Transaction.created_at >= cutoff,
                )
            )
        )
        ranked_transactions = (
            select(
                Transaction.id.label("transaction_id"),
                Transaction.type.label("type"),
                Transaction.created_at.label("date_time"),
                LedgerEntry.account_id.label("account_id"),
                LedgerEntry.direction.label("direction"),
                LedgerEntry.amount_paise.label("amount_paise"),
                LedgerEntry.balance_after_paise.label("balance_after_paise"),
                func.row_number()
                .over(
                    partition_by=Transaction.id,
                    order_by=LedgerEntry.id,
                )
                .label("entry_rank"),
            )
            .join(LedgerEntry, LedgerEntry.txn_id == Transaction.id)
            .where(LedgerEntry.account_id.in_(account_ids))
            .subquery("ranked_user_transactions")
        )
        rows = db.execute(
            select(ranked_transactions)
            .where(ranked_transactions.c.entry_rank == 1)
            .order_by(
                ranked_transactions.c.date_time.desc(),
                ranked_transactions.c.transaction_id.desc(),
            )
            .limit(5)
        ).mappings().all()
        recent_transactions = [
            DashboardTransaction(
                transaction_id=row["transaction_id"],
                type=row["type"],
                date_time=row["date_time"],
                account_id=row["account_id"],
                direction=row["direction"],
                amount_paise=row["amount_paise"],
                balance_after_paise=row["balance_after_paise"],
            )
            for row in rows
        ]

    return DashboardResponse(
        total_balance_paise=sum_account_balances(db, account_ids),
        account_count=len(account_ids),
        transactions_last_30_days=transaction_count,
        role=user.role,
        accounts=dashboard_accounts,
        recent_transactions=recent_transactions,
    )
