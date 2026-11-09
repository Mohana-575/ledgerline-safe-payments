from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.refused_attempt import RefusedAttempt
from tests.factories import (
    assert_books_balance,
    fund_account,
    login_client,
    make_account,
    make_user,
)

REQUEST_REPETITIONS = 3
SMALL_RACE_REPETITIONS = 3


async def _fire_simultaneously(
    client: AsyncClient,
    requests: Sequence[tuple[str, dict[str, int], str]],
) -> list[Response]:
    start = asyncio.Event()

    async def send(
        request: tuple[str, dict[str, int], str],
    ) -> Response:
        path, body, idempotency_key = request
        await start.wait()
        return await client.post(
            path,
            json=body,
            headers={"Idempotency-Key": idempotency_key},
        )

    tasks = [asyncio.create_task(send(request)) for request in requests]
    await asyncio.sleep(0)
    start.set()
    return await asyncio.gather(*tasks)


def _refused_insufficient_funds(
    db_session: Session,
    account_id: int,
) -> int:
    return int(
        db_session.scalar(
            select(func.count())
            .select_from(RefusedAttempt)
            .where(
                RefusedAttempt.account_id == account_id,
                RefusedAttempt.reason_code == "INSUFFICIENT_FUNDS",
            )
        )
    )


def _account_balance(db_session: Session, account_id: int) -> int:
    balance = db_session.scalar(
        select(Account.balance_paise).where(Account.id == account_id)
    )
    assert balance is not None
    return balance


@pytest.mark.asyncio
async def test_simultaneous_withdrawals_cannot_overdraw(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    holder = make_user(db_session)
    db_session.commit()
    client = await login_client(uvicorn_server, holder)
    try:
        for repetition in range(REQUEST_REPETITIONS):
            account = make_account(db_session, holder)
            db_session.commit()
            fund_account(db_session, admin, account, 10_000)

            responses = await _fire_simultaneously(
                client,
                [
                    (
                        "/withdrawals",
                        {"account_id": account.id, "amount_paise": 10_000},
                        f"withdraw-{repetition}-{index}",
                    )
                    for index in range(20)
                ],
            )

            assert sum(response.status_code == 201 for response in responses) == 1
            assert all(response.status_code in {201, 409} for response in responses)
            assert _account_balance(db_session, account.id) == 0
            assert _refused_insufficient_funds(db_session, account.id) == 19
            assert_books_balance(db_session)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_simultaneous_transfers_cannot_overdraw_source(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    holder = make_user(db_session)
    db_session.commit()
    client = await login_client(uvicorn_server, holder)
    try:
        for repetition in range(REQUEST_REPETITIONS):
            accounts = [
                make_account(db_session, holder, name=f"Destination {index}")
                for index in range(31)
            ]
            db_session.commit()
            source, *destinations = accounts
            fund_account(db_session, admin, source, 10_000)

            responses = await _fire_simultaneously(
                client,
                [
                    (
                        "/transfers",
                        {
                            "from_account_id": source.id,
                            "to_account_id": destination.id,
                            "amount_paise": 10_000,
                        },
                        f"transfer-out-{repetition}-{index}",
                    )
                    for index, destination in enumerate(destinations)
                ],
            )

            assert sum(response.status_code == 201 for response in responses) == 1
            assert all(response.status_code in {201, 409} for response in responses)
            assert _account_balance(db_session, source.id) == 0
            assert _refused_insufficient_funds(db_session, source.id) == 29
            assert_books_balance(db_session)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_opposite_direction_transfers_do_not_deadlock(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    holder = make_user(db_session)
    admin = make_user(db_session, role="ADMIN")
    db_session.commit()
    client = await login_client(uvicorn_server, holder)
    try:
        for repetition in range(REQUEST_REPETITIONS):
            account_a = make_account(db_session, holder, name="Account A")
            account_b = make_account(db_session, holder, name="Account B")
            db_session.commit()
            fund_account(db_session, admin, account_a, 1_000_000)
            fund_account(db_session, admin, account_b, 1_000_000)

            requests = [
                (
                    "/transfers",
                    {
                        "from_account_id": account_a.id,
                        "to_account_id": account_b.id,
                        "amount_paise": 1_000,
                    },
                    f"a-to-b-{repetition}-{index}",
                )
                for index in range(50)
            ]
            requests.extend(
                (
                    "/transfers",
                    {
                        "from_account_id": account_b.id,
                        "to_account_id": account_a.id,
                        "amount_paise": 1_000,
                    },
                    f"b-to-a-{repetition}-{index}",
                )
                for index in range(50)
            )
            responses = await _fire_simultaneously(client, requests)

            assert len(responses) == 100
            assert all(response.status_code == 201 for response in responses), [
                (response.status_code, response.text)
                for response in responses
                if response.status_code != 201
            ]
            assert_books_balance(db_session)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_simultaneous_deposits_and_withdrawals_preserve_balance(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    holder = make_user(db_session)
    db_session.commit()
    client = await login_client(uvicorn_server, holder)
    try:
        for repetition in range(SMALL_RACE_REPETITIONS):
            account = make_account(db_session, holder)
            db_session.commit()
            fund_account(db_session, admin, account, 10_000)

            requests = [
                (
                    "/deposits",
                    {"account_id": account.id, "amount_paise": 1_000},
                    f"deposit-{repetition}-{index}",
                )
                for index in range(20)
            ]
            requests.extend(
                (
                    "/withdrawals",
                    {"account_id": account.id, "amount_paise": 1_000},
                    f"withdraw-mixed-{repetition}-{index}",
                )
                for index in range(20)
            )
            responses = await _fire_simultaneously(client, requests)

            assert len(responses) == 40
            assert all(response.status_code == 201 for response in responses), [
                (response.status_code, response.text)
                for response in responses
                if response.status_code != 201
            ]
            assert _account_balance(db_session, account.id) == 10_000
            assert _account_balance(db_session, account.id) >= 0
            assert_books_balance(db_session)
    finally:
        await client.aclose()
