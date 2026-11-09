from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from app.core.security import ACCESS_TOKEN_COOKIE, hash_password
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.user import User
from app.services.ledger import MovementResult, post_movement, reconcile_ledger

DEFAULT_TEST_PASSWORD = "correct horse battery staple"


def make_user(
    db: Session,
    *,
    role: str = "ACCOUNT_HOLDER",
    password: str = DEFAULT_TEST_PASSWORD,
) -> User:
    user = User(
        email=f"test-{uuid.uuid4().hex}@example.com",
        full_name="Test User",
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def make_account(
    db: Session,
    owner: User,
    *,
    name: str = "Test Account",
    account_type: str = "PERSONAL",
) -> Account:
    account = Account(
        account_number=f"TST{uuid.uuid4().hex[:29]}",
        name=name,
        type=account_type,
        is_system=False,
        status="ACTIVE",
    )
    db.add(account)
    db.flush()
    db.add(AccountMember(user_id=owner.id, account_id=account.id))
    db.flush()
    return account


def fund_account(
    db: Session,
    admin: User,
    account: Account,
    amount_paise: int,
) -> MovementResult:
    if admin.role != "ADMIN":
        raise ValueError("fund_account requires an ADMIN user")

    result = post_movement(
        db,
        admin,
        "DEPOSIT",
        from_account_id=None,
        to_account_id=account.id,
        amount_paise=amount_paise,
        idempotency_key=f"test-fund-{uuid.uuid4().hex}",
    )
    if result.response_status != 201:
        raise AssertionError(f"Account funding failed: {result.response_body}")
    return result


def assert_books_balance(db: Session) -> None:
    result = reconcile_ledger(db)
    assert result.total_balance_paise == 0, (
        f"Account balances, including External, sum to "
        f"{result.total_balance_paise} paise"
    )
    assert not result.account_mismatches, (
        f"Account balances differ from their ledger sums: "
        f"{result.account_mismatches}"
    )


async def concurrent_requests(
    client: AsyncClient,
    method: str,
    url: str,
    request_bodies: Sequence[dict[str, Any] | None],
) -> list[Response]:
    start = asyncio.Event()

    async def send(body: dict[str, Any] | None) -> Response:
        await start.wait()
        if body is None:
            return await client.request(method, url)
        return await client.request(method, url, json=body)

    tasks = [asyncio.create_task(send(body)) for body in request_bodies]
    await asyncio.sleep(0)
    start.set()
    return await asyncio.gather(*tasks)


async def login_client(
    base_url: str,
    user: User,
    *,
    password: str = DEFAULT_TEST_PASSWORD,
) -> AsyncClient:
    client = AsyncClient(base_url=base_url, timeout=30)
    response = await client.post(
        "/auth/login",
        json={"email": user.email, "password": password},
    )
    if response.status_code != 200:
        await client.aclose()
        raise AssertionError(
            f"Login failed for {user.email}: "
            f"{response.status_code} {response.text}"
        )
    client.cookies.set(
        ACCESS_TOKEN_COOKIE,
        response.cookies[ACCESS_TOKEN_COOKIE],
        domain="127.0.0.1",
        path="/",
    )
    return client
