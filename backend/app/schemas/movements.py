from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class DepositRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    account_id: StrictInt = Field(gt=0)
    amount_paise: StrictInt


class WithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    account_id: StrictInt = Field(gt=0)
    amount_paise: StrictInt


class TransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    from_account_id: StrictInt = Field(gt=0)
    to_account_id: StrictInt = Field(gt=0)
    amount_paise: StrictInt


class MovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    kind: str
