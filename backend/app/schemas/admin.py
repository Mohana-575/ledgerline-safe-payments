import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AccountBalanceMismatchResponse(BaseModel):
    account_id: int
    account_number: str
    balance_paise: int
    ledger_balance_paise: int


class NegativeAccountBalanceResponse(BaseModel):
    account_id: int
    account_number: str
    balance_paise: int


class TransactionBalanceMismatchResponse(BaseModel):
    transaction_id: uuid.UUID
    debits_paise: int
    credits_paise: int


class ReconciliationResponse(BaseModel):
    passed: bool
    account_balance_sum_paise: int
    accounts_sum_to_zero: bool
    accounts_match_ledger: bool
    account_mismatches: list[AccountBalanceMismatchResponse]
    non_system_accounts_nonnegative: bool
    negative_accounts: list[NegativeAccountBalanceResponse]
    transactions_balanced: bool
    transaction_mismatches: list[TransactionBalanceMismatchResponse]


class LedgerChainStatus(BaseModel):
    account_id: int
    passed: bool
    first_broken_entry_id: int | None


class LedgerVerificationResponse(BaseModel):
    passed: bool
    accounts_checked: int
    accounts: list[LedgerChainStatus]


class DashboardTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    transaction_id: uuid.UUID
    type: Literal["DEPOSIT", "WITHDRAWAL", "TRANSFER"]
    date_time: datetime
    account_id: int
    direction: Literal["DEBIT", "CREDIT"]
    amount_paise: int
    balance_after_paise: int


class DashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    total_balance_paise: int
    account_count: int
    transactions_last_30_days: int
    role: Literal["ADMIN", "ACCOUNT_HOLDER", "AUDITOR"]
    recent_transactions: list[DashboardTransaction]
