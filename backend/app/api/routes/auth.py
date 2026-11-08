import re
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.core.security import (
    ACCESS_TOKEN_COOKIE,
    ACCESS_TOKEN_TTL_SECONDS,
    create_access_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RATE_WINDOW_SECONDS = 60
_RATE_LIMITS = {"login": 10, "register": 5}
_rate_lock = threading.Lock()
_rate_attempts: dict[tuple[str, str], deque[float]] = defaultdict(deque)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: StrictStr = Field(min_length=1, max_length=255)
    email: StrictStr = Field(min_length=3, max_length=320)
    password: StrictStr = Field(min_length=8, max_length=1024)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("full_name must not be blank")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_PATTERN.fullmatch(value):
            raise ValueError("email must be a valid email address")
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: StrictStr = Field(min_length=3, max_length=320)
    password: StrictStr = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_PATTERN.fullmatch(value):
            raise ValueError("email must be a valid email address")
        return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str
    role: str


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


def _check_rate_limit(request: Request, action: str) -> None:
    client_ip = _client_ip(request) or "unknown"
    key = (action, client_ip)
    now = time.monotonic()
    with _rate_lock:
        expired_keys = []
        for existing_key, attempts in _rate_attempts.items():
            while attempts and now - attempts[0] >= _RATE_WINDOW_SECONDS:
                attempts.popleft()
            if not attempts:
                expired_keys.append(existing_key)
        for expired_key in expired_keys:
            del _rate_attempts[expired_key]
        attempts = _rate_attempts[key]
        limit = _RATE_LIMITS[action]
        if len(attempts) >= limit:
            retry_after = max(1, int(_RATE_WINDOW_SECONDS - (now - attempts[0])))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
                headers={"Retry-After": str(retry_after)},
            )
        attempts.append(now)


def _limit_login_requests(request: Request) -> None:
    _check_rate_limit(request, "login")


def _limit_register_requests(request: Request) -> None:
    _check_rate_limit(request, "register")


def _add_audit_log(
    db: Session,
    *,
    action: str,
    request: Request,
    user_id: uuid.UUID | None,
    email: str,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            details={"email": email},
            ip=_client_ip(request),
        )
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=201,
    dependencies=[Depends(_limit_register_requests)],
)
def register(
    body: RegisterRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if db.scalar(select(User.id).where(User.email == body.email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role="ACCOUNT_HOLDER",
    )
    db.add(user)
    try:
        db.flush()
        _add_audit_log(
            db,
            action="REGISTER",
            request=request,
            user_id=user.id,
            email=user.email,
        )
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from exc
    return user


@router.post(
    "/login",
    response_model=UserResponse,
    dependencies=[Depends(_limit_login_requests)],
)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(
        body.password,
        user.password_hash if user is not None else "",
    ):
        _add_audit_log(
            db,
            action="LOGIN_FAILED",
            request=request,
            user_id=user.id if user is not None else None,
            email=body.email,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    _add_audit_log(
        db,
        action="LOGIN_SUCCESS",
        request=request,
        user_id=user.id,
        email=user.email,
    )
    db.commit()
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=create_access_token(user.id),
        max_age=ACCESS_TOKEN_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    response.delete_cookie(
        key=ACCESS_TOKEN_COOKIE,
        path="/",
        httponly=True,
        secure=True,
        samesite="strict",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user
