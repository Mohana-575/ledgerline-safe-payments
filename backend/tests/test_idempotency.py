from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import ACCESS_TOKEN_COOKIE, create_access_token
from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.ledger_entry import LedgerEntry
from app.models.refused_attempt import RefusedAttempt
from app.models.user import User
from tests.factories import (
    concurrent_requests,
    fund_account,
    make_account,
    make_user,
)


def _authenticated_client(base_url: str, user: User) -> AsyncClient:
    client = AsyncClient(base_url=base_url, timeout=30)
    client.cookies.set(
        ACCESS_TOKEN_COOKIE,
        create_access_token(user.id),
        domain="127.0.0.1",
        path="/",
    )
    return client


def _make_holder_account(
    db_session: Session,
    *,
    balance_paise: int = 0,
) -> tuple[User, int]:
    holder = make_user(db_session)
    account = make_account(db_session, holder)
    db_session.commit()
    if balance_paise:
        admin = make_user(db_session, role="ADMIN")
        db_session.commit()
        fund_account(db_session, admin, account, balance_paise)
    return holder, account.id


async def _close_client(client: AsyncClient) -> None:
    await client.aclose()


def _ledger_entry_count(db_session: Session, account_id: int) -> int:
    return int(
        db_session.scalar(
            select(func.count())
            .select_from(LedgerEntry)
            .where(LedgerEntry.account_id == account_id)
        )
    )


def _account_balance(db_session: Session, account_id: int) -> int:
    balance = db_session.scalar(
        select(Account.balance_paise).where(Account.id == account_id)
    )
    assert balance is not None
    return balance


@pytest.mark.asyncio
async def test_same_idempotency_key_replays_sequential_response_once(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    holder, account_id = _make_holder_account(db_session)
    client = _authenticated_client(uvicorn_server, holder)
    try:
        body = {"account_id": account_id, "amount_paise": 1_000}
        headers = {"Idempotency-Key": "sequential-replay-key"}
        first = await client.post("/deposits", json=body, headers=headers)
        replay = await client.post("/deposits", json=body, headers=headers)
    finally:
        await _close_client(client)

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert _account_balance(db_session, account_id) == 1_000
    assert _ledger_entry_count(db_session, account_id) == 1


@pytest.mark.asyncio
async def test_simultaneous_same_key_requests_move_money_once(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    holder, account_id = _make_holder_account(db_session)
    client = _authenticated_client(uvicorn_server, holder)
    key = "simultaneous-replay-key"
    client.headers["Idempotency-Key"] = key
    try:
        responses = await concurrent_requests(
            client,
            "POST",
            "/deposits",
            [{"account_id": account_id, "amount_paise": 1_000}] * 10,
        )
    finally:
        await _close_client(client)

    assert len(responses) == 10
    assert all(response.status_code == 201 for response in responses)
    assert all(response.json() == responses[0].json() for response in responses)
    assert _account_balance(db_session, account_id) == 1_000
    assert _ledger_entry_count(db_session, account_id) == 1


@pytest.mark.asyncio
async def test_same_key_with_different_amount_is_rejected_without_movement(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    holder, account_id = _make_holder_account(db_session)
    client = _authenticated_client(uvicorn_server, holder)
    try:
        first = await client.post(
            "/deposits",
            json={"account_id": account_id, "amount_paise": 1_000},
            headers={"Idempotency-Key": "different-amount-key"},
        )
        changed = await client.post(
            "/deposits",
            json={"account_id": account_id, "amount_paise": 2_000},
            headers={"Idempotency-Key": "different-amount-key"},
        )
    finally:
        await _close_client(client)

    assert first.status_code == 201
    assert changed.status_code == 422
    assert changed.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert _account_balance(db_session, account_id) == 1_000
    assert _ledger_entry_count(db_session, account_id) == 1


@pytest.mark.asyncio
async def test_refused_request_replay_is_identical_and_logged_once(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    holder, account_id = _make_holder_account(db_session)
    client = _authenticated_client(uvicorn_server, holder)
    key = "refused-replay-key"
    try:
        first = await client.post(
            "/withdrawals",
            json={"account_id": account_id, "amount_paise": 1_000},
            headers={"Idempotency-Key": key},
        )
        replay = await client.post(
            "/withdrawals",
            json={"account_id": account_id, "amount_paise": 1_000},
            headers={"Idempotency-Key": key},
        )
    finally:
        await _close_client(client)

    assert first.status_code == replay.status_code == 409
    assert first.json() == replay.json()
    assert first.json()["code"] == "INSUFFICIENT_FUNDS"
    assert _account_balance(db_session, account_id) == 0
    refusals = db_session.scalar(
        select(func.count())
        .select_from(RefusedAttempt)
        .where(
            RefusedAttempt.account_id == account_id,
            RefusedAttempt.idempotency_key == key,
            RefusedAttempt.reason_code == "INSUFFICIENT_FUNDS",
        )
    )
    assert refusals == 1


@pytest.mark.asyncio
async def test_missing_idempotency_key_is_rejected(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    holder, account_id = _make_holder_account(db_session)
    client = _authenticated_client(uvicorn_server, holder)
    try:
        response = await client.post(
            "/deposits",
            json={"account_id": account_id, "amount_paise": 1_000},
        )
    finally:
        await _close_client(client)

    assert response.status_code == 400
    assert _account_balance(db_session, account_id) == 0
    assert _ledger_entry_count(db_session, account_id) == 0


@pytest.mark.asyncio
async def test_same_idempotency_key_is_scoped_to_each_user(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    first_holder, first_account_id = _make_holder_account(db_session)
    second_holder, second_account_id = _make_holder_account(db_session)
    first_client = _authenticated_client(uvicorn_server, first_holder)
    second_client = _authenticated_client(uvicorn_server, second_holder)
    key = "shared-between-users"
    try:
        first = await first_client.post(
            "/deposits",
            json={"account_id": first_account_id, "amount_paise": 1_000},
            headers={"Idempotency-Key": key},
        )
        second = await second_client.post(
            "/deposits",
            json={"account_id": second_account_id, "amount_paise": 1_000},
            headers={"Idempotency-Key": key},
        )
    finally:
        await _close_client(first_client)
        await _close_client(second_client)

    assert first.status_code == second.status_code == 201
    assert first.json() != second.json()
    assert _account_balance(db_session, first_account_id) == 1_000
    assert _account_balance(db_session, second_account_id) == 1_000
    assert _ledger_entry_count(db_session, first_account_id) == 1
    assert _ledger_entry_count(db_session, second_account_id) == 1


@pytest.mark.asyncio
async def test_replays_are_recorded_in_audit_logs(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    holder, account_id = _make_holder_account(db_session)
    key = "audit-replay-key"
    client = _authenticated_client(uvicorn_server, holder)
    try:
        for _ in range(3):
            response = await client.post(
                "/deposits",
                json={"account_id": account_id, "amount_paise": 1_000},
                headers={"Idempotency-Key": key},
            )
            assert response.status_code == 201
    finally:
        await _close_client(client)

    replay_logs = db_session.scalars(
        select(AuditLog).where(
            AuditLog.user_id == holder.id,
            AuditLog.action == "IDEMPOTENT_REPLAY",
        )
    ).all()
    matching_logs = [
        audit for audit in replay_logs if audit.details.get("idempotency_key") == key
    ]
    assert len(matching_logs) == 2
    assert all(log.details["response_status"] == "201" for log in matching_logs)
    assert _account_balance(db_session, account_id) == 1_000
