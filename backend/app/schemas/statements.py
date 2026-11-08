from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

StatementType = Literal[
    "DEPOSIT",
    "WITHDRAWAL",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "REFUSED",
]


class ActorSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    email: str


class StatementEntryResponse(BaseModel):
    date_time: datetime
    type: StatementType
    amount_paise: int | None
    running_balance_paise: int
    status: Literal["COMPLETED", "REFUSED"]
    reason_code: str | None
    initiated_by: ActorSummary | None


class StatementPageResponse(BaseModel):
    items: list[StatementEntryResponse]
    next_cursor: str | None


class AuditLogEntryResponse(BaseModel):
    id: int
    date_time: datetime
    action: str
    details: dict[str, str]
    ip: str | None
    initiated_by: ActorSummary | None


class AuditLogPageResponse(BaseModel):
    items: list[AuditLogEntryResponse]
    next_cursor: str | None


class CursorData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    date_time: datetime
    source: Literal["L", "R", "A"]
    row_id: int


class AuditCursorData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    date_time: datetime
    row_id: int
