import pytest

from tests.factories import (
    DEFAULT_TEST_PASSWORD,
    assert_books_balance,
    concurrent_requests,
    fund_account,
    login_client,
    make_account,
    make_user,
)


@pytest.mark.asyncio
async def test_live_api_supports_concurrent_authenticated_requests(
    db_session,
    uvicorn_server: str,
) -> None:
    admin = make_user(db_session, role="ADMIN")
    holder = make_user(db_session)
    account = make_account(db_session, holder)
    db_session.commit()
    fund_account(db_session, admin, account, 25_000)

    assert_books_balance(db_session)

    client = await login_client(
        uvicorn_server,
        holder,
        password=DEFAULT_TEST_PASSWORD,
    )
    try:
        responses = await concurrent_requests(
            client,
            "GET",
            f"/accounts/{account.id}/balance",
            [None] * 20,
        )
    finally:
        await client.aclose()

    assert len(responses) == 20
    assert all(response.status_code == 200 for response in responses), [
        (response.status_code, response.text)
        for response in responses
        if response.status_code != 200
    ]
    assert all(response.json()["balance_paise"] == 25_000 for response in responses)
