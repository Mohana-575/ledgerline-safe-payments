"""Create users, accounts, and account memberships."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_ledgerline_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('ADMIN', 'ACCOUNT_HOLDER', 'AUDITOR')",
            name="ck_users_role",
        ),
        sa.CheckConstraint(
            "email = lower(email)",
            name="ck_users_email_lowercase",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "accounts",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("account_number", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column(
            "balance_paise",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_entry_hash", sa.Text(), nullable=True),
        sa.Column(
            "is_system",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "type IN ('PERSONAL', 'SAVINGS', 'BUSINESS', 'SYSTEM')",
            name="ck_accounts_type",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'FROZEN')",
            name="ck_accounts_status",
        ),
        sa.CheckConstraint(
            "is_system OR balance_paise >= 0",
            name="ck_accounts_non_system_balance_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_number"),
    )
    op.create_table(
        "account_members",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_account_members_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_account_members_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "account_id"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO accounts (
                account_number,
                name,
                type,
                balance_paise,
                is_system,
                status
            )
            VALUES ('ACC1001', 'External', 'SYSTEM', 0, true, 'ACTIVE')
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM accounts "
            "WHERE account_number = 'ACC1001' "
            "AND name = 'External' "
            "AND type = 'SYSTEM' "
            "AND is_system = true"
        )
    )
    op.drop_table("account_members")
    op.drop_table("accounts")
    op.drop_table("users")
