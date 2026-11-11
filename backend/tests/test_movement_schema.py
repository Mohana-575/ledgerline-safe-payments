import pytest
from app.schemas.movements import TransferRequest
from app.services.ledger import _request_hash
from pydantic import ValidationError


def test_transfer_accepts_account_number_destination() -> None:
    request = TransferRequest(
        from_account_id=12,
        to_account_number=" ACC1001 ",
        amount_paise=2500,
    )

    assert request.to_account_number == "ACC1001"
    assert request.to_account_id is None


def test_transfer_accepts_legacy_account_id_destination() -> None:
    request = TransferRequest(
        from_account_id=12,
        to_account_id=24,
        amount_paise=2500,
    )

    assert request.to_account_id == 24
    assert request.to_account_number is None


@pytest.mark.parametrize(
    "destination",
    ({}, {"to_account_id": 24, "to_account_number": "ACC1001"}),
)
def test_transfer_requires_exactly_one_destination(
    destination: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TransferRequest(
            from_account_id=12,
            amount_paise=2500,
            **destination,
        )


def test_account_number_is_part_of_idempotency_request_hash() -> None:
    first = _request_hash("TRANSFER", 12, None, 2500, "ACC1001")
    same = _request_hash("TRANSFER", 12, None, 2500, "ACC1001")
    different = _request_hash("TRANSFER", 12, None, 2500, "ACC1002")

    assert first == same
    assert first != different
