from enum import StrEnum


class LedgerErrorCode(StrEnum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    FORBIDDEN = "FORBIDDEN"
    INVALID_AMOUNT = "INVALID_AMOUNT"
    ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
    ACCOUNT_FROZEN = "ACCOUNT_FROZEN"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"


class LedgerError(Exception):
    code: LedgerErrorCode
    status_code: int

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InsufficientFundsError(LedgerError):
    code = LedgerErrorCode.INSUFFICIENT_FUNDS
    status_code = 409


class ForbiddenMovementError(LedgerError):
    code = LedgerErrorCode.FORBIDDEN
    status_code = 403


class InvalidAmountError(LedgerError):
    code = LedgerErrorCode.INVALID_AMOUNT
    status_code = 422


class AccountNotFoundError(LedgerError):
    code = LedgerErrorCode.ACCOUNT_NOT_FOUND
    status_code = 404


class AccountFrozenError(LedgerError):
    code = LedgerErrorCode.ACCOUNT_FROZEN
    status_code = 409


class IdempotencyKeyReusedError(LedgerError):
    code = LedgerErrorCode.IDEMPOTENCY_KEY_REUSED
    status_code = 422
