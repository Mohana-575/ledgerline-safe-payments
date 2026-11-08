from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ledger_entry import LedgerEntry
from app.services.ledger import _entry_hash


def verify_chain(db: Session, account_id: int) -> int | None:
    entries = db.scalars(
        select(LedgerEntry)
        .where(LedgerEntry.account_id == account_id)
        .order_by(LedgerEntry.id)
    ).all()

    previous_hash: str | None = None
    for entry in entries:
        if entry.prev_hash != previous_hash:
            return entry.id

        expected_hash = _entry_hash(
            txn_id=entry.txn_id,
            account_id=entry.account_id,
            direction=entry.direction,
            amount_paise=entry.amount_paise,
            balance_after_paise=entry.balance_after_paise,
            initiated_by=entry.initiated_by,
            prev_hash=entry.prev_hash,
            created_at=entry.created_at,
        )
        if entry.hash != expected_hash:
            return entry.id
        previous_hash = entry.hash

    return None
