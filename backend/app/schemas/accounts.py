import uuid
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
)
from pydantic_core import PydanticCustomError

AccountType = Literal["PERSONAL", "SAVINGS", "BUSINESS"]


def _parse_uuid(value: object) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        raise PydanticCustomError(
            "uuid_type",
            "user_id must be a UUID string",
        )
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise PydanticCustomError(
            "uuid_format",
            "user_id must be a valid UUID",
        ) from exc


class AccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: StrictStr = Field(min_length=1, max_length=255)
    type: AccountType

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class MemberAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    user_id: Annotated[uuid.UUID, BeforeValidator(_parse_uuid)]


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_number: str
    name: str
    type: str
    balance_paise: int
    status: str


class AccountBalanceResponse(BaseModel):
    account_id: int
    balance_paise: int


class MemberAssignmentResponse(BaseModel):
    account_id: int
    user_id: uuid.UUID
