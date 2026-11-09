from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import ACCESS_TOKEN_COOKIE, create_access_token
from app.models.account import Account
from app.models.ledger_entry import LedgerEntry
from app.models.user import User
from tests.factories import fund_account, make_account, make_user

_INVALID_AMOUNTS: tuple[object, ...] = (
    1.0,
    "100",
    True,
    None,
    1e30,
    0,
    -5,
    10**19,
    get_settings().MAX_AMOUNT_PAISE + 1,
)


def _client(base_url: str, user: User) -> AsyncClient:
    client = AsyncClient(base_url=base_url, timeout=30)
    client.cookies.set(
        ACCESS_TOKEN_COOKIE,
        create_access_token(user.id),
        domain="127.0.0.1",
        path="/",
    )
    return client


def _movement_body(
    path: str,
    source_id: int,
    destination_id: int,
    amount: object,
) -> dict[str, object]:
    if path == "/deposits":
        return {"account_id": destination_id, "amount_paise": amount}
    if path == "/withdrawals":
        return {"account_id": source_id, "amount_paise": amount}
    return {
        "from_account_id": source_id,
        "to_account_id": destination_id,
        "amount_paise": amount,
    }


def _ledger_count(db_session: Session) -> int:
    return int(db_session.scalar(select(func.count()).select_from(LedgerEntry)))


def _account_balances(db_session: Session) -> dict[int, int]:
    return dict(db_session.execute(select(Account.id, Account.balance_paise)).all())


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/deposits", "/withdrawals", "/transfers"])
async def test_money_endpoints_reject_invalid_amounts_without_ledger_entries(
    path: str,
    db_session: Session,
    uvicorn_server: str,
) -> None:
    holder = make_user(db_session)
    source = make_account(db_session, holder)
    destination = make_account(db_session, holder)
    db_session.commit()
    initial_ledger_count = _ledger_count(db_session)
    initial_balances = _account_balances(db_session)

    client = _client(uvicorn_server, holder)
    try:
        for index, amount in enumerate(_INVALID_AMOUNTS):
            response: Response = await client.post(
                path,
                json=_movement_body(path, source.id, destination.id, amount),
                headers={"Idempotency-Key": f"invalid-amount-{uuid.uuid4().hex}"},
            )
            assert 400 <= response.status_code < 500, (
                f"{path} accepted amount {amount!r}: "
                f"{response.status_code} {response.text}"
            )
            assert response.status_code != 500
            assert _ledger_count(db_session) == initial_ledger_count, index
            assert _account_balances(db_session) == initial_balances, index
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/deposits", "/withdrawals", "/transfers"])
async def test_money_endpoints_accept_exact_maximum_amount(
    path: str,
    db_session: Session,
    uvicorn_server: str,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    holder = make_user(db_session)
    source = make_account(db_session, holder)
    destination = make_account(db_session, holder)
    db_session.commit()

    maximum = get_settings().MAX_AMOUNT_PAISE
    if path != "/deposits":
        fund_account(db_session, admin, source, maximum)
    initial_ledger_count = _ledger_count(db_session)

    client = _client(uvicorn_server, holder)
    try:
        response = await client.post(
            path,
            json=_movement_body(path, source.id, destination.id, maximum),
            headers={"Idempotency-Key": f"maximum-amount-{uuid.uuid4().hex}"},
        )
    finally:
        await client.aclose()

    assert response.status_code == 201, response.text
    assert _ledger_count(db_session) == initial_ledger_count + 2
