from __future__ import annotations

import uuid

import pytest
from app.core.security import ACCESS_TOKEN_COOKIE, create_access_token
from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.ledger_entry import LedgerEntry
from app.models.refused_attempt import RefusedAttempt
from app.models.user import User
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.factories import fund_account, make_account, make_user


def _client(base_url: str, user: User) -> AsyncClient:
    client = AsyncClient(base_url=base_url, timeout=30)
    client.cookies.set(
        ACCESS_TOKEN_COOKIE,
        create_access_token(user.id),
        domain="127.0.0.1",
        path="/",
    )
    return client


def _ledger_count(db_session: Session) -> int:
    return int(db_session.scalar(select(func.count()).select_from(LedgerEntry)))


def _refusal_count(
    db_session: Session,
    *,
    user_id: uuid.UUID,
    account_id: int,
) -> int:
    return int(
        db_session.scalar(
            select(func.count())
            .select_from(RefusedAttempt)
            .where(
                RefusedAttempt.user_id == user_id,
                RefusedAttempt.account_id == account_id,
            )
        )
    )


def _balance(db_session: Session, account_id: int) -> int:
    balance = db_session.scalar(
        select(Account.balance_paise).where(Account.id == account_id)
    )
    assert balance is not None
    return balance


async def _close(*clients: AsyncClient) -> None:
    for client in clients:
        await client.aclose()


@pytest.mark.asyncio
async def test_holder_cannot_withdraw_or_transfer_from_another_holders_account(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    holder_x = make_user(db_session)
    holder_y = make_user(db_session)
    holder_x_account = make_account(db_session, holder_x)
    holder_y_account = make_account(db_session, holder_y)
    db_session.commit()
    fund_account(db_session, admin, holder_y_account, 20_000)
    balance_before = _balance(db_session, holder_y_account.id)
    ledger_before = _ledger_count(db_session)

    client = _client(uvicorn_server, holder_x)
    try:
        withdrawal = await client.post(
            "/withdrawals",
            json={"account_id": holder_y_account.id, "amount_paise": 1_000},
            headers={"Idempotency-Key": "x-withdraw-y-account"},
        )
        transfer = await client.post(
            "/transfers",
            json={
                "from_account_id": holder_y_account.id,
                "to_account_id": holder_x_account.id,
                "amount_paise": 1_000,
            },
            headers={"Idempotency-Key": "x-transfer-y-account"},
        )
    finally:
        await _close(client)

    assert withdrawal.status_code in {403, 404}
    assert transfer.status_code in {403, 404}
    assert _balance(db_session, holder_y_account.id) == balance_before
    assert _ledger_count(db_session) == ledger_before
    assert (
        _refusal_count(
            db_session,
            user_id=holder_x.id,
            account_id=holder_y_account.id,
        )
        == 2
    )


@pytest.mark.asyncio
async def test_withdrawal_hides_nonexistent_and_nonmember_account_difference(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    holder = make_user(db_session)
    other_holder = make_user(db_session)
    other_account = make_account(db_session, other_holder)
    db_session.commit()
    nonexistent_account_id = 9_000_000_000_000_000_000

    client = _client(uvicorn_server, holder)
    try:
        nonexistent = await client.post(
            "/withdrawals",
            json={
                "account_id": nonexistent_account_id,
                "amount_paise": 1_000,
            },
            headers={"Idempotency-Key": "missing-account-withdrawal"},
        )
        nonmember = await client.post(
            "/withdrawals",
            json={"account_id": other_account.id, "amount_paise": 1_000},
            headers={"Idempotency-Key": "nonmember-account-withdrawal"},
        )
    finally:
        await _close(client)

    nonexistent_body = nonexistent.json()
    nonmember_body = nonmember.json()
    assert nonexistent.status_code == nonmember.status_code, (
        f"nonexistent={nonexistent.status_code} {nonexistent_body}; "
        f"nonmember={nonmember.status_code} {nonmember_body}"
    )
    assert nonexistent_body["code"] == nonmember_body["code"]
    assert nonexistent_body["message"] == nonmember_body["message"]


@pytest.mark.asyncio
async def test_holder_cannot_deposit_into_nonmember_account(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    holder_x = make_user(db_session)
    holder_y = make_user(db_session)
    account_y = make_account(db_session, holder_y)
    db_session.commit()
    fund_account(db_session, admin, account_y, 5_000)
    balance_before = _balance(db_session, account_y.id)
    ledger_before = _ledger_count(db_session)

    client = _client(uvicorn_server, holder_x)
    try:
        response = await client.post(
            "/deposits",
            json={"account_id": account_y.id, "amount_paise": 1_000},
            headers={"Idempotency-Key": "x-deposit-y-account"},
        )
    finally:
        await _close(client)

    assert response.status_code == 403
    assert _balance(db_session, account_y.id) == balance_before
    assert _ledger_count(db_session) == ledger_before
    assert (
        _refusal_count(
            db_session,
            user_id=holder_x.id,
            account_id=account_y.id,
        )
        == 1
    )


@pytest.mark.asyncio
async def test_holder_cannot_transfer_to_external_system_account(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    holder = make_user(db_session)
    source_account = make_account(db_session, holder)
    external_account = db_session.scalar(
        select(Account).where(
            Account.account_number == "ACC1000",
            Account.is_system.is_(True),
        )
    )
    assert external_account is not None
    db_session.commit()
    fund_account(db_session, admin, source_account, 10_000)

    balances_before = dict(
        db_session.execute(
            select(Account.id, Account.balance_paise)
        ).all()
    )
    ledger_before = _ledger_count(db_session)
    refusals_before = _refusal_count(
        db_session,
        user_id=holder.id,
        account_id=source_account.id,
    )

    client = _client(uvicorn_server, holder)
    try:
        response = await client.post(
            "/transfers",
            json={
                "from_account_id": source_account.id,
                "to_account_id": external_account.id,
                "amount_paise": 1_000,
            },
            headers={"Idempotency-Key": "transfer-to-external"},
        )
    finally:
        await _close(client)

    balances_after = dict(
        db_session.execute(
            select(Account.id, Account.balance_paise)
        ).all()
    )
    assert response.status_code in {403, 422}
    assert balances_after == balances_before
    assert _ledger_count(db_session) == ledger_before
    assert (
        _refusal_count(
            db_session,
            user_id=holder.id,
            account_id=source_account.id,
        )
        == refusals_before + 1
    )


@pytest.mark.asyncio
async def test_holder_can_transfer_to_account_number(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    holder = make_user(db_session)
    destination_owner = make_user(db_session)
    source = make_account(db_session, holder)
    destination = make_account(db_session, destination_owner)
    db_session.commit()
    fund_account(db_session, admin, source, 10_000)

    client = _client(uvicorn_server, holder)
    try:
        response = await client.post(
            "/transfers",
            json={
                "from_account_id": source.id,
                "to_account_number": destination.account_number,
                "amount_paise": 1_000,
            },
            headers={"Idempotency-Key": f"account-number-{uuid.uuid4().hex}"},
        )
    finally:
        await _close(client)

    assert response.status_code == 201, response.text
    assert response.json()["kind"] == "TRANSFER"
    assert _balance(db_session, source.id) == 9_000
    assert _balance(db_session, destination.id) == 1_000


@pytest.mark.asyncio
async def test_auditor_is_denied_money_and_admin_write_endpoints(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    holder = make_user(db_session)
    auditor = make_user(db_session, role="AUDITOR")
    account = make_account(db_session, holder)
    destination = make_account(db_session, holder, name="Auditor Transfer Destination")
    db_session.commit()
    fund_account(db_session, admin, account, 5_000)
    balance_before = _balance(db_session, account.id)
    ledger_before = _ledger_count(db_session)
    client = _client(uvicorn_server, auditor)
    try:
        responses = [
            await client.post(
                "/deposits",
                json={"account_id": account.id, "amount_paise": 1_000},
                headers={"Idempotency-Key": "auditor-deposit-denied"},
            ),
            await client.post(
                "/withdrawals",
                json={"account_id": account.id, "amount_paise": 1_000},
                headers={"Idempotency-Key": "auditor-withdraw-denied"},
            ),
            await client.post(
                "/transfers",
                json={
                    "from_account_id": account.id,
                    "to_account_id": destination.id,
                    "amount_paise": 1_000,
                },
                headers={"Idempotency-Key": "auditor-transfer-denied"},
            ),
            await client.post(
                "/accounts",
                json={"name": "Auditor Account", "type": "PERSONAL"},
            ),
            await client.post(
                f"/accounts/{account.id}/members",
                json={"user_id": str(auditor.id)},
            ),
        ]
    finally:
        await _close(client)

    assert [response.status_code for response in responses] == [
        403,
        403,
        403,
        403,
        403,
    ]
    assert _balance(db_session, account.id) == balance_before
    assert _ledger_count(db_session) == ledger_before
    assert (
        _refusal_count(
            db_session,
            user_id=auditor.id,
            account_id=account.id,
        )
        == 3
    )


@pytest.mark.asyncio
async def test_holder_is_denied_account_creation_assignment_and_admin_routes(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    holder = make_user(db_session)
    account = make_account(db_session, holder)
    target = make_user(db_session)
    db_session.commit()
    ledger_before = _ledger_count(db_session)
    client = _client(uvicorn_server, holder)
    try:
        responses = [
            await client.post(
                "/accounts",
                json={"name": "Holder Created Account", "type": "PERSONAL"},
            ),
            await client.post(
                f"/accounts/{account.id}/members",
                json={"user_id": str(target.id)},
            ),
            await client.get("/admin/reconcile"),
            await client.get("/admin/verify-ledger"),
        ]
    finally:
        await _close(client)

    assert [response.status_code for response in responses] == [403] * 4
    assert _ledger_count(db_session) == ledger_before


@pytest.mark.asyncio
async def test_admin_cannot_debit_accounts_without_membership(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    owner = make_user(db_session)
    destination_owner = make_user(db_session)
    source = make_account(db_session, owner)
    destination = make_account(db_session, destination_owner)
    db_session.commit()
    fund_account(db_session, admin, source, 5_000)
    balance_before = _balance(db_session, source.id)
    ledger_before = _ledger_count(db_session)

    client = _client(uvicorn_server, admin)
    try:
        withdrawal = await client.post(
            "/withdrawals",
            json={"account_id": source.id, "amount_paise": 1_000},
            headers={"Idempotency-Key": "admin-withdraw-nonmember"},
        )
        transfer = await client.post(
            "/transfers",
            json={
                "from_account_id": source.id,
                "to_account_id": destination.id,
                "amount_paise": 1_000,
            },
            headers={"Idempotency-Key": "admin-transfer-nonmember"},
        )
    finally:
        await _close(client)

    assert withdrawal.status_code == transfer.status_code == 403
    assert _balance(db_session, source.id) == balance_before
    assert _ledger_count(db_session) == ledger_before
    assert (
        _refusal_count(
            db_session,
            user_id=admin.id,
            account_id=source.id,
        )
        == 2
    )


@pytest.mark.asyncio
async def test_registration_rejects_role_injection_and_assigns_holder_role(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    client = AsyncClient(base_url=uvicorn_server, timeout=30)
    try:
        rejected = await client.post(
            "/auth/register",
            json={
                "full_name": "Role Injection",
                "email": f"role-injection-{uuid.uuid4().hex}@example.com",
                "password": "valid-password-123",
                "role": "ADMIN",
            },
        )
        registered_email = f"registered-{uuid.uuid4().hex}@example.com"
        registered = await client.post(
            "/auth/register",
            json={
                "full_name": "Normal Holder",
                "email": registered_email,
                "password": "valid-password-123",
            },
        )
    finally:
        await client.aclose()

    assert rejected.status_code == 422
    assert registered.status_code == 201
    assert registered.json()["role"] == "ACCOUNT_HOLDER"
    stored_user = db_session.scalar(select(User).where(User.email == registered_email))
    assert stored_user is not None
    assert stored_user.role == "ACCOUNT_HOLDER"


@pytest.mark.asyncio
async def test_unauthenticated_requests_are_rejected_except_public_routes(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    owner = make_user(db_session)
    account = make_account(db_session, owner)
    target = make_user(db_session)
    db_session.commit()
    client = AsyncClient(base_url=uvicorn_server, timeout=30)
    try:
        health = await client.get("/health")
        login = await client.post(
            "/auth/login",
            json={"email": owner.email, "password": "wrong-password"},
        )
        registration = await client.post(
            "/auth/register",
            json={
                "full_name": "Public Registration",
                "email": f"public-{uuid.uuid4().hex}@example.com",
                "password": "valid-password-123",
            },
        )
        logout = await client.post("/auth/logout")
        protected_responses: list[Response] = [
            await client.get("/auth/me"),
            await client.get("/accounts"),
            await client.get(f"/accounts/{account.id}"),
            await client.get(f"/accounts/{account.id}/balance"),
            await client.get(f"/accounts/{account.id}/statement"),
            await client.get("/audit-logs"),
            await client.get("/dashboard"),
            await client.get("/admin/reconcile"),
            await client.get("/admin/verify-ledger"),
            await client.post(
                "/accounts",
                json={"name": "Unauthenticated Account", "type": "PERSONAL"},
            ),
            await client.post(
                f"/accounts/{account.id}/members",
                json={"user_id": str(target.id)},
            ),
            await client.post(
                "/deposits",
                json={"account_id": account.id, "amount_paise": 1_000},
                headers={"Idempotency-Key": "unauth-deposit"},
            ),
            await client.post(
                "/withdrawals",
                json={"account_id": account.id, "amount_paise": 1_000},
                headers={"Idempotency-Key": "unauth-withdraw"},
            ),
            await client.post(
                "/transfers",
                json={
                    "from_account_id": account.id,
                    "to_account_id": account.id + 100,
                    "amount_paise": 1_000,
                },
                headers={"Idempotency-Key": "unauth-transfer"},
            ),
        ]
    finally:
        await client.aclose()

    assert health.status_code == 200
    assert login.status_code == 401
    assert registration.status_code == 201
    assert logout.status_code == 204
    assert [response.status_code for response in protected_responses] == [401] * len(
        protected_responses
    )


@pytest.mark.asyncio
async def test_holder_cannot_read_other_users_statement_balance_or_audit_logs(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    holder = make_user(db_session)
    other_holder = make_user(db_session)
    other_account = make_account(db_session, other_holder)
    db_session.add(
        AuditLog(
            user_id=other_holder.id,
            action="PRIVATE_AUDIT_MARKER",
            details={"marker": "another-users-private-event"},
        )
    )
    db_session.commit()

    client = _client(uvicorn_server, holder)
    try:
        statement = await client.get(f"/accounts/{other_account.id}/statement")
        balance = await client.get(f"/accounts/{other_account.id}/balance")
        audit_logs = await client.get("/audit-logs")
    finally:
        await _close(client)

    assert statement.status_code == 404
    assert balance.status_code == 404
    assert audit_logs.status_code == 200
    audit_items = audit_logs.json()["items"]
    assert all(
        item["details"].get("marker") != "another-users-private-event"
        for item in audit_items
    )
    assert all(
        item["initiated_by"] is None
        or item["initiated_by"]["email"] != other_holder.email
        for item in audit_items
    )


@pytest.mark.asyncio
async def test_database_role_change_applies_to_existing_token(
    db_session: Session,
    uvicorn_server: str,
) -> None:
    holder = make_user(db_session)
    db_session.commit()
    client = _client(uvicorn_server, holder)
    try:
        before_change = await client.get("/admin/reconcile")
        holder.role = "AUDITOR"
        db_session.commit()
        after_change = await client.get("/admin/reconcile")
    finally:
        await _close(client)

    assert before_change.status_code == 403
    assert after_change.status_code == 200
