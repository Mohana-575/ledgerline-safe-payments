import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

ACCESS_TOKEN_COOKIE = "access_token"
ACCESS_TOKEN_TTL_SECONDS = 15 * 60
_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError):
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
        },
        get_settings().JWT_SECRET,
        algorithm="HS256",
    )


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(
            token,
            get_settings().JWT_SECRET,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
        subject = payload.get("sub")
        if not isinstance(subject, str):
            return None
        return uuid.UUID(subject)
    except (jwt.PyJWTError, ValueError, TypeError):
        return None
