"""A notification reaching a device: asked for once, sealed for that device,
and the device forgotten when its push service says it is gone."""

from __future__ import annotations

import json
import uuid

import asyncpg
import pytest

from conftest import PHONE, SALES_1, SALES_2, TENANT_A, PushService, open_push, reseed_with_people
from dealerai.config import get_settings
from dealerai.db.session import tenant_session
from dealerai.events.bus import Event
from dealerai.events.handlers import notify as notifications

CONVERSATION = "11111111-1111-4111-8111-111111111111"


async def _device(
    su: asyncpg.Connection, user: uuid.UUID = SALES_1, endpoint: str = PHONE["endpoint"]
) -> uuid.UUID:
    return await su.fetchval(  # type: ignore[no-any-return]
        """insert into push_subscriptions (tenant_id, user_id, endpoint, p256dh, auth)
           values ($1, $2, $3, $4, $5) returning id""",
        TENANT_A,
        user,
        endpoint,
        PHONE["p256dh"],
        PHONE["auth"],
    )


async def _tell(kind: str = "assigned", dedupe: str = "a") -> None:
    """What a handler does when somebody should know: notify(), in the worker's session."""
    async with tenant_session(TENANT_A) as conn:
        await notifications.notify(
            conn,
            tenant_id=TENANT_A,
            user_id=SALES_1,
            kind=kind,
            title="A customer is waiting for you",
            body="Omar Haddad",
            entity={"type": "conversation", "id": CONVERSATION},
            dedupe_key=dedupe,
        )


async def _requested(su: asyncpg.Connection) -> list[Event]:
    """The pushes asked for, as the worker would claim them."""
    rows = await su.fetch(
        """select id, tenant_id, event_type, payload, dedupe_key from events
            where event_type = 'notification.push_requested' order by id"""
    )
    return [
        Event(
            id=r["id"],
            tenant_id=r["tenant_id"],
            event_type=r["event_type"],
            payload=json.loads(r["payload"]),
            attempts=1,
            dedupe_key=r["dedupe_key"],
        )
        for r in rows
    ]


async def _push(su: asyncpg.Connection) -> None:
    """One notification worth a push, and the worker getting to it."""
    await _tell()
    [event] = await _requested(su)
    await notifications.on_push_requested(event)


async def _failures(su: asyncpg.Connection, device: uuid.UUID) -> int | None:
    return await su.fetchval(  # type: ignore[no-any-return]
        "select failure_count from push_subscriptions where id = $1", device
    )


# --------------------------------------------------------------------------
# asking
# --------------------------------------------------------------------------


async def test_a_notification_worth_a_push_asks_for_one_once(
    db: None, su: asyncpg.Connection
) -> None:
    await reseed_with_people()
    await _tell()
    await _tell()  # the queue retried whatever told them

    note = await su.fetchval("select id from notifications")  # one row, or this raises
    assert await su.fetchval("select count(*) from notifications") == 1
    [event] = await _requested(su)
    assert event.payload == {"notification_id": str(note)}
    assert await su.fetchval("select priority from events where id = $1", event.id) == 8


async def test_the_rest_stay_in_the_bell(db: None, su: asyncpg.Connection) -> None:
    """A customer's every message, and whatever arrives in batches."""
    await reseed_with_people()
    await _tell(kind="message_received", dedupe="a")
    await _tell(kind="brief_ready", dedupe="b")
    await _tell(kind="followup_ready", dedupe="c")

    assert await su.fetchval("select count(*) from notifications") == 3
    assert await _requested(su) == []


# --------------------------------------------------------------------------
# sending
# --------------------------------------------------------------------------


async def test_the_device_gets_what_was_said_sealed_for_it(
    db: None, su: asyncpg.Connection, push_service: PushService
) -> None:
    await reseed_with_people()
    device = await _device(su)

    await _push(su)

    [request] = push_service.requests
    assert str(request.url) == PHONE["endpoint"]
    assert open_push(request.content) == {
        "title": "A customer is waiting for you",
        "body": "Omar Haddad",
        "href": f"/alpha/inbox/{CONVERSATION}",
        "tag": "assigned",
    }
    assert request.headers["Content-Encoding"] == "aes128gcm"
    assert request.headers["TTL"] == "3600" and request.headers["Urgency"] == "high"
    assert request.headers["Authorization"].startswith("vapid t=")
    assert await su.fetchval(
        "select last_success_at is not null from push_subscriptions where id = $1", device
    )


@pytest.mark.parametrize("gone", [404, 410])
async def test_a_device_that_is_gone_is_forgotten(
    db: None, su: asyncpg.Connection, push_service: PushService, gone: int
) -> None:
    await reseed_with_people()
    await _device(su)
    push_service.status = gone

    await _push(su)

    assert await su.fetchval("select count(*) from push_subscriptions") == 0


async def test_a_push_service_having_a_bad_day_is_counted_not_forgotten(
    db: None, su: asyncpg.Connection, push_service: PushService
) -> None:
    await reseed_with_people()
    device = await _device(su)
    push_service.status = 500
    await _tell()
    [event] = await _requested(su)

    await notifications.on_push_requested(event)
    assert await _failures(su, device) == 1

    push_service.status = 201
    await notifications.on_push_requested(event)
    assert await _failures(su, device) == 0


async def test_a_push_service_that_cannot_be_reached_fails_nothing(
    db: None, su: asyncpg.Connection, push_service: PushService
) -> None:
    await reseed_with_people()
    device = await _device(su)
    push_service.unreachable = True

    await _push(su)

    assert await _failures(su, device) == 1


async def test_with_no_key_nothing_is_sent_and_nothing_fails(
    db: None,
    su: asyncpg.Connection,
    push_service: PushService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server nobody set a key on: the bell works as before."""
    await reseed_with_people()
    await _device(su)
    monkeypatch.setattr(get_settings(), "vapid_private_key", None)

    await _push(su)

    assert push_service.requests == []


async def test_only_its_readers_devices_hear(
    db: None, su: asyncpg.Connection, push_service: PushService
) -> None:
    await reseed_with_people()
    await _device(su)
    await _device(su, SALES_2, "https://fcm.googleapis.com/fcm/send/somebody-else")

    await _push(su)

    assert [str(request.url) for request in push_service.requests] == [PHONE["endpoint"]]


async def test_a_reader_with_no_device_costs_nothing(
    db: None, su: asyncpg.Connection, push_service: PushService
) -> None:
    await reseed_with_people()

    await _push(su)

    assert push_service.requests == []


async def test_a_notification_gone_by_then_is_not_an_error(
    db: None, su: asyncpg.Connection, push_service: PushService
) -> None:
    await reseed_with_people()
    await _device(su)
    await _tell()
    [event] = await _requested(su)
    await su.execute("delete from notifications")

    await notifications.on_push_requested(event)

    assert push_service.requests == []
