import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import ACCESS_TOKEN_COOKIE, decode_access_token
from app.db.session import get_db
from app.models.user import User

AUTHENTICATED_ROLES = frozenset({"ADMIN", "ACCOUNT_HOLDER", "AUDITOR"})


def current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    user_id: uuid.UUID | None = decode_access_token(token) if token else None
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    if not roles or any(role not in AUTHENTICATED_ROLES for role in roles):
        raise ValueError("require_roles needs one or more valid user roles")

    def role_dependency(
        user: Annotated[User, Depends(current_user)],
    ) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return role_dependency
