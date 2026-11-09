"""Move the External account to ACC1000."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_external_account_number"
down_revision: str | None = "0003_idempotency_pending"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE accounts
            SET account_number = 'ACC1000'
            WHERE account_number = 'ACC1001' AND is_system = true
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE accounts
            SET account_number = 'ACC1001'
            WHERE account_number = 'ACC1000' AND is_system = true
            """
        )
    )
