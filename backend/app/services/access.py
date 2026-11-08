import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account_member import AccountMember


def get_member_account_ids(db: Session, user_id: uuid.UUID) -> list[int]:
    return list(
        db.scalars(
            select(AccountMember.account_id).where(AccountMember.user_id == user_id)
        ).all()
    )


def assert_member(db: Session, user_id: uuid.UUID, account_id: int) -> None:
    membership = db.scalar(
        select(AccountMember.user_id)
        .where(
            AccountMember.user_id == user_id,
            AccountMember.account_id == account_id,
        )
        .limit(1)
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account membership required",
        )
