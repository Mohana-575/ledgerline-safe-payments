import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, require_roles
from app.db.session import get_db
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.accounts import (
    AccountBalanceResponse,
    AccountCreateRequest,
    AccountResponse,
    MemberAssignmentResponse,
    MemberAssignRequest,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])
_ACCOUNT_NUMBER_PATTERN = re.compile(r"^ACC([0-9]+)$")
_ACCOUNT_NUMBER_LOCK_KEY = 731_204_119


def _next_account_number(db: Session) -> str:
    db.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:lock_key AS BIGINT))"),
        {"lock_key": _ACCOUNT_NUMBER_LOCK_KEY},
    )
    existing_numbers = db.scalars(
        select(Account.account_number).where(
            Account.account_number.op("~")(r"^ACC[0-9]+$")
        )
    ).all()
    highest_number = max(
        (
            int(match.group(1))
            for account_number in existing_numbers
            if (match := _ACCOUNT_NUMBER_PATTERN.fullmatch(account_number))
        ),
        default=0,
    )
    return f"ACC{highest_number + 1:04d}"


def _add_account_audit_log(
    db: Session,
    *,
    action: str,
    actor_id: uuid.UUID,
    request: Request,
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


def _visible_account(
    db: Session,
    user: User,
    account_id: int,
) -> Account:
    if user.role in {"ADMIN", "AUDITOR"}:
        account = db.scalar(select(Account).where(Account.id == account_id))
    elif user.role == "ACCOUNT_HOLDER":
        account = db.scalar(
            select(Account)
            .join(
                AccountMember,
                AccountMember.account_id == Account.id,
            )
            .where(
                Account.id == account_id,
                AccountMember.user_id == user.id,
            )
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )
    return account


@router.post(
    "",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_account(
    body: AccountCreateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(require_roles("ADMIN"))],
) -> Account:
    account = Account(
        account_number=_next_account_number(db),
        name=body.name,
        type=body.type,
        balance_paise=0,
        is_system=False,
        status="ACTIVE",
    )
    db.add(account)
    try:
        db.flush()
        _add_account_audit_log(
            db,
            action="ACCOUNT_CREATED",
            actor_id=admin.id,
            request=request,
            details={
                "account_id": str(account.id),
                "account_number": account.account_number,
            },
        )
        db.commit()
        db.refresh(account)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unable to create account",
        ) from exc
    return account


@router.post(
    "/{account_id}/members",
    response_model=MemberAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def assign_member(
    account_id: int,
    body: MemberAssignRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(require_roles("ADMIN"))],
) -> MemberAssignmentResponse:
    if db.get(Account, account_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )
    if db.get(User, body.user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if db.get(AccountMember, (body.user_id, account_id)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this account",
        )

    db.add(AccountMember(user_id=body.user_id, account_id=account_id))
    _add_account_audit_log(
        db,
        action="MEMBER_ASSIGNED",
        actor_id=admin.id,
        request=request,
        details={"account_id": str(account_id), "user_id": str(body.user_id)},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this account",
        ) from exc
    return MemberAssignmentResponse(account_id=account_id, user_id=body.user_id)


@router.get("", response_model=list[AccountResponse])
def list_accounts(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> list[Account]:
    statement = select(Account).order_by(Account.id)
    if user.role == "ACCOUNT_HOLDER":
        statement = (
            statement.join(
                AccountMember,
                AccountMember.account_id == Account.id,
            )
            .where(AccountMember.user_id == user.id)
            .distinct()
        )
    elif user.role not in {"ADMIN", "AUDITOR"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return list(db.scalars(statement).all())


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(
    account_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> Account:
    return _visible_account(db, user, account_id)


@router.get("/{account_id}/balance", response_model=AccountBalanceResponse)
def get_account_balance(
    account_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> AccountBalanceResponse:
    account = _visible_account(db, user, account_id)
    return AccountBalanceResponse(
        account_id=account.id,
        balance_paise=account.balance_paise,
    )
