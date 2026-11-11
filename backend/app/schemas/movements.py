from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


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
    to_account_id: StrictInt | None = Field(default=None, gt=0)
    to_account_number: StrictStr | None = Field(
        default=None, min_length=1, max_length=32
    )
    amount_paise: StrictInt

    @field_validator("to_account_number")
    @classmethod
    def normalize_account_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("to_account_number must not be blank")
        return value

    @model_validator(mode="after")
    def validate_destination(self) -> "TransferRequest":
        if (self.to_account_id is None) == (self.to_account_number is None):
            raise ValueError("Provide exactly one transfer destination")
        return self


class MovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    kind: str
