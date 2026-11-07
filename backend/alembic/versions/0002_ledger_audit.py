"""Create ledger, idempotency, refusal, and audit tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_ledger_audit"
down_revision: str | None = "0001_ledgerline_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_TABLES = (
    "transactions",
    "ledger_entries",
    "refused_attempts",
    "audit_logs",
)


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("initiated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "type IN ('DEPOSIT', 'WITHDRAWAL', 'TRANSFER')",
            name="ck_transactions_type",
        ),
        sa.ForeignKeyConstraint(
            ["initiated_by"],
            ["users.id"],
            name="fk_transactions_initiated_by_users",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ledger_entries",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("txn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("direction", sa.String(length=6), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_paise", sa.BigInteger(), nullable=False),
        sa.Column("initiated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("prev_hash", sa.Text(), nullable=True),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "direction IN ('DEBIT', 'CREDIT')",
            name="ck_ledger_entries_direction",
        ),
        sa.CheckConstraint(
            "amount_paise > 0",
            name="ck_ledger_entries_amount_positive",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_ledger_entries_account_id_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["initiated_by"],
            ["users.id"],
            name="fk_ledger_entries_initiated_by_users",
        ),
        sa.ForeignKeyConstraint(
            ["txn_id"],
            ["transactions.id"],
            name="fk_ledger_entries_txn_id_transactions",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "refused_attempts",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_refused_attempts_account_id_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_refused_attempts_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_idempotency_keys_user_id_users",
        ),
        sa.PrimaryKeyConstraint("user_id", "key"),
    )
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_audit_logs_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(
        """
        CREATE FUNCTION reject_append_only_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Table % is append-only; % is not permitted',
                TG_TABLE_NAME, TG_OP
                USING ERRCODE = '55000';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_append_only_truncate()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Table % is append-only; TRUNCATE is not permitted',
                TG_TABLE_NAME
                USING ERRCODE = '55000';
        END;
        $$;
        """
    )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_update_delete
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION reject_append_only_mutation();
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_truncate
            BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT
            EXECUTE FUNCTION reject_append_only_truncate();
            """
        )

    op.execute(
        """
        CREATE FUNCTION check_ledger_transaction_balanced()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            debit_total numeric;
            credit_total numeric;
        BEGIN
            SELECT
                COALESCE(SUM(amount_paise) FILTER (WHERE direction = 'DEBIT'), 0),
                COALESCE(SUM(amount_paise) FILTER (WHERE direction = 'CREDIT'), 0)
            INTO debit_total, credit_total
            FROM ledger_entries
            WHERE txn_id = NEW.txn_id;

            IF debit_total <> credit_total THEN
                RAISE EXCEPTION
                    'Transaction % is unbalanced: debits %, credits %',
                    NEW.txn_id, debit_total, credit_total
                    USING ERRCODE = '23514';
            END IF;

            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER ledger_entries_transaction_balanced
        AFTER INSERT OR UPDATE ON ledger_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION check_ledger_transaction_balanced();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS ledger_entries_transaction_balanced "
        "ON ledger_entries"
    )
    op.execute("DROP FUNCTION IF EXISTS check_ledger_transaction_balanced()")
    for table in reversed(APPEND_ONLY_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_truncate ON {table}")
        op.execute(
            f"DROP TRIGGER IF EXISTS {table}_reject_update_delete ON {table}"
        )
    op.execute("DROP FUNCTION IF EXISTS reject_append_only_truncate()")
    op.execute("DROP FUNCTION IF EXISTS reject_append_only_mutation()")
    for table in (
        "audit_logs",
        "idempotency_keys",
        "refused_attempts",
        "ledger_entries",
        "transactions",
    ):
        op.drop_table(table)
