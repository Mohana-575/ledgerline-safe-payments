import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import (
    String,
    and_,
    case,
    func,
    literal,
    select,
    tuple_,
    union_all,
)
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.api.routes.accounts import _visible_account
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.ledger_entry import LedgerEntry
from app.models.refused_attempt import RefusedAttempt
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.statements import (
    ActorSummary,
    AuditCursorData,
    AuditLogEntryResponse,
    AuditLogPageResponse,
    CursorData,
    StatementEntryResponse,
    StatementPageResponse,
)

router = APIRouter(tags=["statements"])
_StatementFilter = Literal[
    "DEPOSIT",
    "WITHDRAWAL",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "REFUSED",
    "ALL",
]


def _encode_cursor(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


def _decode_cursor(cursor: str | None, model: type[CursorData] | type[AuditCursorData]):
    if cursor is None:
        return None
    try:
        encoded = cursor.encode("ascii")
        decoded = base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))
        if len(decoded) > 1024:
            raise ValueError("Cursor is too long")
        if model is CursorData:
            return CursorData.model_validate_json(decoded, strict=True)
        return AuditCursorData.model_validate_json(decoded, strict=True)
    except (
        UnicodeEncodeError,
        binascii.Error,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid cursor",
        ) from exc


def _aware_utc(value: datetime | None, name: str) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{name} must include a timezone",
        )
    return value.astimezone(UTC) if value is not None else None


def _validate_time_range(
    from_time: datetime | None,
    to_time: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    from_time = _aware_utc(from_time, "from")
    to_time = _aware_utc(to_time, "to")
    if from_time is not None and to_time is not None and from_time > to_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="'from' must be earlier than or equal to 'to'",
        )
    return from_time, to_time


def _statement_query(
    account_id: int,
    *,
    statement_type: _StatementFilter,
    from_time: datetime | None,
    to_time: datetime | None,
    cursor: CursorData | None,
):
    entry_type = case(
        (Transaction.type == "DEPOSIT", literal("DEPOSIT")),
        (Transaction.type == "WITHDRAWAL", literal("WITHDRAWAL")),
        (
            and_(
                Transaction.type == "TRANSFER",
                LedgerEntry.direction == "CREDIT",
            ),
            literal("TRANSFER_IN"),
        ),
        else_=literal("TRANSFER_OUT"),
    )
    signed_entry_amount = case(
        (LedgerEntry.direction == "DEBIT", -LedgerEntry.amount_paise),
        else_=LedgerEntry.amount_paise,
    )
    ledger_query = (
        select(
            literal("L", type_=String()).label("source"),
            LedgerEntry.id.label("row_id"),
            LedgerEntry.created_at.label("date_time"),
            entry_type.label("type"),
            signed_entry_amount.label("amount_paise"),
            LedgerEntry.balance_after_paise.label("running_balance_paise"),
            literal("COMPLETED", type_=String()).label("status"),
            literal(None, type_=String()).label("reason_code"),
            User.full_name.label("initiated_by_name"),
            User.email.label("initiated_by_email"),
        )
        .join(Transaction, Transaction.id == LedgerEntry.txn_id)
        .join(User, User.id == LedgerEntry.initiated_by)
        .where(LedgerEntry.account_id == account_id)
    )
    if statement_type not in {"ALL", "REFUSED"}:
        ledger_query = ledger_query.where(entry_type == statement_type)
    elif statement_type == "REFUSED":
        ledger_query = ledger_query.where(False)

    latest_balance = (
        select(LedgerEntry.balance_after_paise)
        .where(
            LedgerEntry.account_id == account_id,
            LedgerEntry.created_at < RefusedAttempt.created_at,
        )
        .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    refused_query = (
        select(
            literal("R", type_=String()).label("source"),
            RefusedAttempt.id.label("row_id"),
            RefusedAttempt.created_at.label("date_time"),
            literal("REFUSED", type_=String()).label("type"),
            case(
                (RefusedAttempt.type == "DEPOSIT", RefusedAttempt.amount_paise),
                else_=-RefusedAttempt.amount_paise,
            ).label("amount_paise"),
            func.coalesce(latest_balance, 0).label("running_balance_paise"),
            literal("REFUSED", type_=String()).label("status"),
            RefusedAttempt.reason_code.label("reason_code"),
            User.full_name.label("initiated_by_name"),
            User.email.label("initiated_by_email"),
        )
        .join(User, User.id == RefusedAttempt.user_id)
        .where(RefusedAttempt.account_id == account_id)
    )
    if statement_type != "ALL":
        refused_query = refused_query.where(statement_type == "REFUSED")

    rows = union_all(ledger_query, refused_query).subquery("statement_rows")
    query = select(rows)
    if from_time is not None:
        query = query.where(rows.c.date_time >= from_time)
    if to_time is not None:
        query = query.where(rows.c.date_time <= to_time)
    if cursor is not None:
        query = query.where(
            tuple_(rows.c.date_time, rows.c.source, rows.c.row_id)
            > tuple_(cursor.date_time, cursor.source, cursor.row_id)
        )
    return query.order_by(rows.c.date_time, rows.c.source, rows.c.row_id)


@router.get(
    "/accounts/{account_id}/statement",
    response_model=StatementPageResponse,
)
def get_account_statement(
    account_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    statement_type: Annotated[_StatementFilter, Query(alias="type")] = "ALL",
    from_time: Annotated[datetime | None, Query(alias="from")] = None,
    to_time: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> StatementPageResponse:
    _visible_account(db, user, account_id)
    from_time, to_time = _validate_time_range(from_time, to_time)
    decoded_cursor = _decode_cursor(cursor, CursorData)
    result = db.execute(
        _statement_query(
            account_id,
            statement_type=statement_type,
            from_time=from_time,
            to_time=to_time,
            cursor=decoded_cursor,
        ).limit(limit + 1)
    ).mappings().all()
    has_more = len(result) > limit
    rows = result[:limit]
    items = [
        StatementEntryResponse(
            date_time=row["date_time"],
            type=row["type"],
            amount_paise=row["amount_paise"],
            running_balance_paise=row["running_balance_paise"],
            status=row["status"],
            reason_code=row["reason_code"],
            initiated_by=(
                ActorSummary(
                    name=row["initiated_by_name"],
                    email=row["initiated_by_email"],
                )
                if row["initiated_by_name"] is not None
                else None
            ),
        )
        for row in rows
    ]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(
            {
                "date_time": last["date_time"].isoformat(),
                "source": last["source"],
                "row_id": last["row_id"],
            }
        )
    return StatementPageResponse(items=items, next_cursor=next_cursor)


@router.get("/audit-logs", response_model=AuditLogPageResponse)
def get_audit_logs(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    action: str | None = None,
    from_time: Annotated[datetime | None, Query(alias="from")] = None,
    to_time: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> AuditLogPageResponse:
    if user.role not in {"ADMIN", "AUDITOR", "ACCOUNT_HOLDER"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    from_time, to_time = _validate_time_range(from_time, to_time)
    decoded_cursor = _decode_cursor(cursor, AuditCursorData)
    query = (
        select(AuditLog, User.full_name, User.email)
        .outerjoin(User, User.id == AuditLog.user_id)
        .order_by(AuditLog.created_at, AuditLog.id)
    )
    if user.role == "ACCOUNT_HOLDER":
        query = query.where(AuditLog.user_id == user.id)
    if action is not None:
        query = query.where(AuditLog.action == action)
    if from_time is not None:
        query = query.where(AuditLog.created_at >= from_time)
    if to_time is not None:
        query = query.where(AuditLog.created_at <= to_time)
    if decoded_cursor is not None:
        query = query.where(
            tuple_(AuditLog.created_at, AuditLog.id)
            > tuple_(decoded_cursor.date_time, decoded_cursor.row_id)
        )
    result = db.execute(query.limit(limit + 1)).all()
    has_more = len(result) > limit
    rows = result[:limit]
    items = [
        AuditLogEntryResponse(
            id=audit.id,
            date_time=audit.created_at,
            action=audit.action,
            details=audit.details,
            ip=audit.ip,
            initiated_by=(
                ActorSummary(name=full_name, email=email)
                if full_name is not None
                else None
            ),
        )
        for audit, full_name, email in rows
    ]
    next_cursor = None
    if has_more and rows:
        last_audit = rows[-1][0]
        next_cursor = _encode_cursor(
            {
                "date_time": last_audit.created_at.isoformat(),
                "row_id": last_audit.id,
            }
        )
    return AuditLogPageResponse(items=items, next_cursor=next_cursor)
