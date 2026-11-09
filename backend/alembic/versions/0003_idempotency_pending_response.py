"""Allow idempotency rows to be claimed before their response is available."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_idempotency_pending"
down_revision: str | None = "0002_ledger_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "idempotency_keys",
        "response_status",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "idempotency_keys",
        "response_body",
        existing_type=postgresql.JSONB(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "idempotency_keys",
        "response_body",
        existing_type=postgresql.JSONB(),
        nullable=False,
    )
    op.alter_column(
        "idempotency_keys",
        "response_status",
        existing_type=sa.Integer(),
        nullable=False,
    )
