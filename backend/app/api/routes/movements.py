import re
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.movements import (
    DepositRequest,
    MovementResponse,
    TransferRequest,
    WithdrawalRequest,
)
from app.services.ledger import post_movement

router = APIRouter(tags=["ledger"])
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def _validate_idempotency_key(key: str | None) -> str:
    if key is None or not _IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid Idempotency-Key header is required",
        )
    return key


@router.post("/deposits", response_model=MovementResponse, status_code=201)
def post_deposit(
    body: DepositRequest,
    _request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(current_user)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    result = post_movement(
        db,
        actor,
        "DEPOSIT",
        from_account_id=None,
        to_account_id=body.account_id,
        amount_paise=body.amount_paise,
        idempotency_key=_validate_idempotency_key(idempotency_key),
    )
    return JSONResponse(
        status_code=result.response_status,
        content=result.response_body,
    )


@router.post("/withdrawals", response_model=MovementResponse, status_code=201)
def post_withdrawal(
    body: WithdrawalRequest,
    _request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(current_user)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    result = post_movement(
        db,
        actor,
        "WITHDRAWAL",
        from_account_id=body.account_id,
        to_account_id=None,
        amount_paise=body.amount_paise,
        idempotency_key=_validate_idempotency_key(idempotency_key),
    )
    return JSONResponse(
        status_code=result.response_status,
        content=result.response_body,
    )


@router.post("/transfers", response_model=MovementResponse, status_code=201)
def post_transfer(
    body: TransferRequest,
    _request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(current_user)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    result = post_movement(
        db,
        actor,
        "TRANSFER",
        from_account_id=body.from_account_id,
        to_account_id=body.to_account_id,
        amount_paise=body.amount_paise,
        idempotency_key=_validate_idempotency_key(idempotency_key),
    )
    return JSONResponse(
        status_code=result.response_status,
        content=result.response_body,
    )
