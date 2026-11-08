import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RefusedAttempt(Base):
    __tablename__ = "refused_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    account_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id"),
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_paise: Mapped[int | None] = mapped_column(BigInteger)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
