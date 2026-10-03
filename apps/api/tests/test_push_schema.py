"""Where a push goes: a device somebody subscribed, theirs and nobody else's."""

from __future__ import annotations

import uuid

from conftest import SALES_1, SALES_2, TENANT_A, reseed_with_people
from dealerai.db.session import tenant_session

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc"


async def _subscribe(user: uuid.UUID, endpoint: str = ENDPOINT) -> uuid.UUID:
    async with tenant_session(TENANT_A, user_id=user, scope="own") as conn:
        return await conn.fetchval(  # type: ignore[no-any-return]
            "select app.remember_push_subscription($1, $2, $3, 'p256dh', 'auth', 'Chrome')",
            TENANT_A,
            user,
            endpoint,
        )


async def _count(user: uuid.UUID | None) -> int:
    async with tenant_session(TENANT_A, user_id=user, scope="own") as conn:
        return await conn.fetchval(  # type: ignore[no-any-return]
            "select count(*) from push_subscriptions"
        )


async def test_a_device_is_its_owners_and_nobody_elses(db: None) -> None:
    await reseed_with_people()
    await _subscribe(SALES_1)
    assert await _count(SALES_1) == 1
    assert await _count(SALES_2) == 0
    # The worker has no user in its session: it reads everybody's, to send.
    assert await _count(None) == 1


async def test_a_device_belongs_to_whoever_subscribed_it_last(db: None) -> None:
    """A shared phone that changes hands must not keep telling the last person."""
    await reseed_with_people()
    await _subscribe(SALES_1)
    await _subscribe(SALES_2)
    async with tenant_session(TENANT_A) as conn:
        owners = [r["user_id"] for r in await conn.fetch("select user_id from push_subscriptions")]
    assert owners == [SALES_2]


async def test_one_person_may_have_several_devices(db: None) -> None:
    await reseed_with_people()
    await _subscribe(SALES_1)
    await _subscribe(SALES_1, f"{ENDPOINT}-laptop")
    assert await _count(SALES_1) == 2
