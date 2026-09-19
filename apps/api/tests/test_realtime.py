"""Who hears which live update, and what a stream sends when nothing happens."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid

import asyncpg

from conftest import MANAGER, SALES_1, SALES_2, TEAM_LOCAL, TENANT_A, TENANT_B, USER_A
from dealerai import realtime
from dealerai.realtime import Hub, Subscriber

CONVERSATION = uuid.uuid4()


def _payload(**overrides: object) -> str:
    payload: dict[str, object] = {
        "tenant_id": str(TENANT_A),
        "type": "message.created",
        "id": str(uuid.uuid4()),
        "conversation_id": str(CONVERSATION),
        "owner_id": str(SALES_1),
        "assigned_to": str(SALES_1),
        "team_id": str(TEAM_LOCAL),
        "user_id": None,
    }
    payload.update(overrides)
    return json.dumps(payload)


def _subscriber(
    user_id: uuid.UUID, scope: str, visible: set[uuid.UUID] | None = None
) -> Subscriber:
    return Subscriber(
        tenant_id=TENANT_A,
        user_id=user_id,
        scope=scope,
        visible_owner_ids={SALES_1} if visible is None else visible,
        team_ids={TEAM_LOCAL},
    )


async def test_another_tenant_never_hears_anything() -> None:
    hub = Hub()
    listener = hub.subscribe(_subscriber(SALES_1, "own"))
    hub.publish(_payload(tenant_id=str(TENANT_B)))
    assert listener.queue.empty()


async def test_a_salesperson_hears_their_own_conversation() -> None:
    hub = Hub()
    listener = hub.subscribe(_subscriber(SALES_1, "own"))
    hub.publish(_payload())
    assert json.loads(await listener.queue.get())["conversation_id"] == str(CONVERSATION)


async def test_a_salesperson_does_not_hear_a_colleagues() -> None:
    hub = Hub()
    listener = hub.subscribe(_subscriber(SALES_2, "own", visible={SALES_2}))
    hub.publish(_payload())
    assert listener.queue.empty(), "a live update leaked across salespeople"


async def test_whoever_is_assigned_hears_it_even_without_owning_it() -> None:
    """Covering for a colleague: the conversation is assigned to me today."""
    hub = Hub()
    listener = hub.subscribe(_subscriber(SALES_2, "own", visible={SALES_2}))
    hub.publish(_payload(assigned_to=str(SALES_2)))
    assert not listener.queue.empty()


async def test_a_manager_hears_their_teams_unassigned_queue() -> None:
    hub = Hub()
    listener = hub.subscribe(_subscriber(MANAGER, "team", visible={SALES_1, SALES_2}))
    hub.publish(_payload(owner_id=None, assigned_to=None))
    assert not listener.queue.empty()


async def test_an_owner_hears_everything_in_the_tenant() -> None:
    hub = Hub()
    listener = hub.subscribe(_subscriber(MANAGER, "all", visible=set()))
    hub.publish(_payload(owner_id=str(SALES_2), assigned_to=str(SALES_2), team_id=None))
    assert not listener.queue.empty()


async def test_a_notification_reaches_only_its_person() -> None:
    hub = Hub()
    mine = hub.subscribe(_subscriber(SALES_1, "own"))
    theirs = hub.subscribe(_subscriber(SALES_2, "own", visible={SALES_2}))
    hub.publish(
        _payload(
            type="notification.created",
            user_id=str(SALES_1),
            conversation_id=None,
            owner_id=None,
            assigned_to=None,
        )
    )
    assert not mine.queue.empty()
    assert theirs.queue.empty()


async def test_a_slow_reader_is_dropped_rather_than_remembered() -> None:
    """A tab that stopped reading must not grow a queue forever; it refetches
    when it comes back."""
    hub = Hub(max_queued=2)
    listener = hub.subscribe(_subscriber(SALES_1, "own"))
    for _ in range(5):
        hub.publish(_payload())
    assert listener.queue.qsize() == 2
    assert listener.dropped == 3


async def test_an_unreadable_payload_does_not_take_the_process_down() -> None:
    hub = Hub()
    listener = hub.subscribe(_subscriber(SALES_1, "own"))
    hub.publish("not json at all")
    assert listener.queue.empty()


async def test_a_write_in_postgres_reaches_a_subscriber(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    """The whole chain, once: trigger → NOTIFY → the process's listener → a tab.

    The unit tests above know nothing about whether the trigger fires or what it
    names its event, which is exactly what breaks when a migration is edited.
    """
    stop = asyncio.Event()
    listener = asyncio.create_task(realtime.listen(stop))
    subscriber = realtime.hub.subscribe(
        Subscriber(
            tenant_id=TENANT_A,
            user_id=USER_A,
            scope="all",
            visible_owner_ids=set(),
            team_ids=set(),
        )
    )
    try:
        await asyncio.sleep(0.2)  # let the listener attach before writing
        conversation_id = await su.fetchval(
            "select id from conversations where tenant_id = $1", TENANT_A
        )
        await su.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender, origin, body)
               values ($1, $2, 'in', 'customer', 'customer', 'live from postgres')""",
            TENANT_A,
            conversation_id,
        )
        event = json.loads(await asyncio.wait_for(subscriber.queue.get(), timeout=5))
    finally:
        realtime.hub.unsubscribe(subscriber)
        stop.set()
        listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener

    assert event["type"] == "message.created"
    assert event["conversation_id"] == str(conversation_id)


async def test_unsubscribing_stops_delivery() -> None:
    hub = Hub()
    listener = hub.subscribe(_subscriber(SALES_1, "own"))
    hub.unsubscribe(listener)
    hub.publish(_payload())
    assert listener.queue.empty()
    assert hub.open_streams == 0
