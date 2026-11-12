import argparse
import os
import secrets
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.user import User
from app.services.ledger import (
    EXTERNAL_ACCOUNT_NUMBER,
    post_movement,
    reconcile_ledger,
)

_SEED_LOCK_KEY = 731_204_120


@dataclass(frozen=True)
class SeedUser:
    email: str
    full_name: str
    role: str


_USERS = (
    SeedUser("admin@example.com", "Administrator", "ADMIN"),
    SeedUser("auditor@example.com", "Auditor", "AUDITOR"),
    SeedUser("user1@example.com", "Hide", "ACCOUNT_HOLDER"),
)
_USER_ACCOUNTS = (
    ("ACC1001", "Personal", "PERSONAL", 7_500_000),
    ("ACC1002", "Savings", "SAVINGS", 5_000_000),
)


def _lock_seed(db: Session) -> None:
    db.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:lock_key AS BIGINT))"),
        {"lock_key": _SEED_LOCK_KEY},
    )


def _get_or_create_users(
    db: Session,
    configured_password: str | None,
    *,
    reset_passwords: bool = False,
) -> tuple[dict[str, User], list[tuple[str, str]]]:
    users: dict[str, User] = {}
    generated_credentials: list[tuple[str, str]] = []
    for seed_user in _USERS:
        user = db.scalar(select(User).where(User.email == seed_user.email))
        if user is not None:
            if user.role != seed_user.role:
                raise RuntimeError(
                    f"{seed_user.email} exists with role {user.role}, "
                    f"expected {seed_user.role}"
                )
            if reset_passwords:
                if configured_password is None:
                    raise ValueError(
                        "SEED_PASSWORD is required to reset seeded passwords"
                    )
                user.password_hash = hash_password(configured_password)
            users[seed_user.email] = user
            continue

        password = configured_password or secrets.token_urlsafe(24)
        user = User(
            email=seed_user.email,
            full_name=seed_user.full_name,
            password_hash=hash_password(password),
            role=seed_user.role,
        )
        db.add(user)
        db.flush()
        users[seed_user.email] = user
        if configured_password is None:
            generated_credentials.append((seed_user.email, password))
    return users, generated_credentials


def _get_or_create_account(
    db: Session,
    *,
    account_number: str,
    name: str,
    account_type: str,
) -> Account:
    account = db.scalar(
        select(Account).where(Account.account_number == account_number)
    )
    if account is not None:
        if (
            account.is_system
            or account.name != name
            or account.type != account_type
        ):
            raise RuntimeError(
                f"{account_number} already exists but is not the expected "
                f"{name} {account_type} account"
            )
        return account

    account = Account(
        account_number=account_number,
        name=name,
        type=account_type,
        is_system=False,
        status="ACTIVE",
    )
    db.add(account)
    db.flush()
    return account


def _ensure_external_account(db: Session) -> None:
    external_account = db.scalar(
        select(Account).where(
            Account.account_number == EXTERNAL_ACCOUNT_NUMBER,
            Account.is_system.is_(True),
        )
    )
    if external_account is None:
        raise RuntimeError(
            "The External account is not at ACC1000; run "
            "`alembic upgrade head` before seeding"
        )


def _ensure_seed_accounts(
    db: Session,
    holder: User,
) -> dict[str, Account]:
    accounts: dict[str, Account] = {}
    for account_number, name, account_type, _amount_paise in _USER_ACCOUNTS:
        account = _get_or_create_account(
            db,
            account_number=account_number,
            name=name,
            account_type=account_type,
        )
        membership = db.get(AccountMember, (holder.id, account.id))
        if membership is None:
            db.add(AccountMember(user_id=holder.id, account_id=account.id))
        accounts[account_number] = account
    return accounts


def _assert_reconciled(db: Session) -> None:
    result = reconcile_ledger(db)
    if (
        result.total_balance_paise != 0
        or result.account_mismatches
        or result.negative_accounts
        or result.transaction_mismatches
    ):
        raise RuntimeError(
            "Ledger reconciliation failed after seeding: "
            f"total_balance_paise={result.total_balance_paise}, "
            f"account_mismatches={len(result.account_mismatches)}, "
            f"negative_accounts={len(result.negative_accounts)}, "
            f"transaction_mismatches={len(result.transaction_mismatches)}"
        )


def seed(
    db: Session,
    configured_password: str | None = None,
    *,
    reset_passwords: bool = False,
) -> None:
    if configured_password == "":
        raise ValueError("SEED_PASSWORD must not be empty")
    if reset_passwords and configured_password is None:
        raise ValueError("SEED_PASSWORD is required to reset seeded passwords")

    _lock_seed(db)
    _ensure_external_account(db)
    users, generated_credentials = _get_or_create_users(
        db,
        configured_password,
        reset_passwords=reset_passwords,
    )
    admin = users["admin@example.com"]
    holder = users["user1@example.com"]
    accounts = _ensure_seed_accounts(db, holder)
    db.commit()

    if generated_credentials:
        print("Generated seed credentials (save them securely):")
        for email, password in generated_credentials:
            print(f"{email}: {password}")

    for account_number, _name, _account_type, amount_paise in _USER_ACCOUNTS:
        result = post_movement(
            db,
            admin,
            "DEPOSIT",
            from_account_id=None,
            to_account_id=accounts[account_number].id,
            amount_paise=amount_paise,
            idempotency_key=f"seed-deposit-{account_number.lower()}-v1",
        )
        if result.response_status != 201:
            raise RuntimeError(
                f"Deposit to {account_number} failed: "
                f"{result.response_body.get('code', 'UNKNOWN')}: "
                f"{result.response_body.get('message', 'No details')}"
            )

    _assert_reconciled(db)
    print("Seed complete. Ledger reconciliation passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the application database.")
    parser.add_argument(
        "--reset-passwords",
        action="store_true",
        help="Reset passwords for existing seeded users using SEED_PASSWORD.",
    )
    args = parser.parse_args()
    configured_password = os.environ.get("SEED_PASSWORD")
    if args.reset_passwords and configured_password is None:
        parser.error("--reset-passwords requires SEED_PASSWORD to be set")
    with SessionLocal() as db:
        seed(
            db,
            configured_password,
            reset_passwords=args.reset_passwords,
        )


if __name__ == "__main__":
    main()
