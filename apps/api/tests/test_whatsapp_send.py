"""Outbound WhatsApp sends are queued idempotently and never double-sent."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
import pytest

from conftest import TENANT_A, USER_A
from dealerai.connectors.base import (
    ConnectorError,
    MessageRequest,
    MessageResult,
    OutsideMessagingWindow,
    RateLimited,
    RequestRejected,
)
from dealerai.core.security import AuthedUser
from dealerai.deps import TenantContext
from dealerai.events.bus import Event
from dealerai.events.handlers import whatsapp
from dealerai.routes.inbox import SendMessageIn, send_message

CHANNEL = UUID("aaaaaaaa-1111-4111-8111-111111111111")


class FakeConnector:
    def __init__(self) -> None:
        self.requests: list[MessageRequest] = []

    async def send_message(self, request: MessageRequest) -> MessageResult:
        self.requests.append(request)
        return MessageResult(external_id="wamid.out-1")


def _ctx() -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_A,
        user=AuthedUser(id=USER_A, email="alpha@example.test", claims={}),
        role="owner",
    )


async def _conversation(
    su: asyncpg.Connection,
    *,
    window_open: bool = True,
    consent: dict[str, object] | None = None,
) -> UUID:
    await su.execute(
        """insert into channels (id, tenant_id, platform, external_id, account_id, mode)
           values ($1, $2, 'whatsapp', 'phone-1', 'waba-1', 'cloud_api')""",
        CHANNEL,
        TENANT_A,
    )
    contact_id = await su.fetchval(
        """insert into contacts (tenant_id, full_name, consent)
           values ($1, 'Karim', $2) returning id""",
        TENANT_A,
        json.dumps(consent or {}),
    )
    await su.execute(
        """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
           values ($1, $2, 'whatsapp_user_id', 'AE.13491208655302741918', true)""",
        TENANT_A,
        contact_id,
    )
    return UUID(
        str(
            await su.fetchval(
                """insert into conversations
                     (tenant_id, contact_id, channel_id, surface, wa_window_expires_at)
                   values ($1, $2, $3, 'whatsapp', $4) returning id""",
                TENANT_A,
                contact_id,
                CHANNEL,
                datetime.now(UTC) + (timedelta(hours=1) if window_open else -timedelta(hours=1)),
            )
        )
    )


async def test_text_send_is_queued_once_for_an_idempotency_key(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    conversation_id = await _conversation(su)
    body = SendMessageIn(text="Yes, it is available.")

    first = await send_message(conversation_id, body, "send-1", _ctx())
    replay = await send_message(conversation_id, body, "send-1", _ctx())

    assert first.id == replay.id
    assert first.status == "queued"
    assert (
        await su.fetchval(
            "select count(*) from messages where tenant_id=$1 and idempotency_key='send-1'",
            TENANT_A,
        )
        == 1
    )
    [event] = await su.fetch("select event_type, priority from events")
    assert (event["event_type"], event["priority"]) == ("whatsapp.send_requested", 10)


async def test_free_form_send_is_refused_after_the_customer_window_closes(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    conversation_id = await _conversation(su, window_open=False)
    with pytest.raises(OutsideMessagingWindow):
        await send_message(
            conversation_id, SendMessageIn(text="Still interested?"), "send-closed", _ctx()
        )
    assert (
        await su.fetchval(
            "select count(*) from messages where tenant_id=$1 and direction='out'", TENANT_A
        )
        == 0
    )


async def test_send_handler_claims_calls_meta_and_records_the_external_id_once(
    db: None,
    su: asyncpg.Connection,
    seeded: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _conversation(su)
    queued = await send_message(
        conversation_id, SendMessageIn(text="Yes, it is available."), "send-2", _ctx()
    )
    connector = FakeConnector()
    monkeypatch.setattr(whatsapp, "whatsapp_for_channel", lambda channel: connector)
    event = Event(
        id=20,
        tenant_id=TENANT_A,
        event_type="whatsapp.send_requested",
        payload={"message_id": str(queued.id)},
        attempts=1,
        dedupe_key=f"send:{queued.id}",
    )

    await whatsapp.on_send_requested(event)
    await whatsapp.on_send_requested(event)

    assert len(connector.requests) == 1
    assert connector.requests[0].recipient_external_id == "AE.13491208655302741918"
    row = await su.fetchrow("select status, external_id from messages where id=$1", queued.id)
    assert row is not None and (row["status"], row["external_id"]) == (
        "sent",
        "wamid.out-1",
    )


class FailingConnector:
    """A connector that refuses every send with one prepared failure."""

    def __init__(self, failure: Exception) -> None:
        self.failure = failure
        self.requests: list[MessageRequest] = []

    async def send_message(self, request: MessageRequest) -> MessageResult:
        self.requests.append(request)
        raise self.failure


async def _queued_send(su: asyncpg.Connection, key: str) -> UUID:
    conversation_id = await _conversation(su)
    queued = await send_message(
        conversation_id, SendMessageIn(text="Yes, it is available."), key, _ctx()
    )
    return queued.id


def _send_event(message_id: UUID) -> Event:
    return Event(
        id=30,
        tenant_id=TENANT_A,
        event_type="whatsapp.send_requested",
        payload={"message_id": str(message_id)},
        attempts=1,
        dedupe_key=f"send:{message_id}",
    )


async def test_a_rate_limit_returns_the_message_to_the_queue(
    db: None, su: asyncpg.Connection, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meta refused to accept it, so the customer's reply is still unsent — and
    must be tried again rather than marked failed."""
    message_id = await _queued_send(su, "send-rate-limited")
    connector = FailingConnector(RateLimited("slow down", retry_after_seconds=30))
    monkeypatch.setattr(whatsapp, "whatsapp_for_channel", lambda channel: connector)

    with pytest.raises(RateLimited):
        await whatsapp.on_send_requested(_send_event(message_id))

    row = await su.fetchrow("select status, locked_at, error from messages where id=$1", message_id)
    assert row is not None and row["status"] == "queued"
    assert row["locked_at"] is None and row["error"] is None


async def test_meta_s_refusal_fails_the_message_with_its_cause(
    db: None, su: asyncpg.Connection, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    message_id = await _queued_send(su, "send-rejected")
    connector = FailingConnector(RequestRejected("Recipient cannot be reached", code="131026"))
    monkeypatch.setattr(whatsapp, "whatsapp_for_channel", lambda channel: connector)

    await whatsapp.on_send_requested(_send_event(message_id))

    row = await su.fetchrow("select status, error from messages where id=$1", message_id)
    assert row is not None and row["status"] == "failed"
    error = json.loads(row["error"])
    assert error["code"] == "131026"
    assert "cannot be reached" in error["message"]


async def test_an_ambiguous_failure_is_left_to_the_watchdog(
    db: None, su: asyncpg.Connection, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout or a 5xx may mean Meta already delivered it.

    Marking it `failed` here would invite a Retry that sends the customer the
    same message twice, so the row stays `sending` until the watchdog calls the
    delivery unknown.
    """
    message_id = await _queued_send(su, "send-timeout")
    connector = FailingConnector(ConnectorError("the WhatsApp Cloud API timed out"))
    monkeypatch.setattr(whatsapp, "whatsapp_for_channel", lambda channel: connector)

    with pytest.raises(ConnectorError):
        await whatsapp.on_send_requested(_send_event(message_id))

    row = await su.fetchrow("select status, locked_at, error from messages where id=$1", message_id)
    assert row is not None and row["status"] == "sending"
    assert row["locked_at"] is not None and row["error"] is None

    # The retry finds it already claimed and sends nothing a second time.
    await whatsapp.on_send_requested(_send_event(message_id))
    assert len(connector.requests) == 1


async def test_watchdog_never_resends_an_unknown_delivery(
    db: None,
    su: asyncpg.Connection,
    seeded: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _conversation(su)
    queued = await send_message(
        conversation_id, SendMessageIn(text="Yes, it is available."), "send-3", _ctx()
    )
    await su.execute(
        "update messages set status='sending', locked_at=now()-interval '3 minutes' where id=$1",
        queued.id,
    )
    connector = FakeConnector()
    monkeypatch.setattr(whatsapp, "whatsapp_for_channel", lambda channel: connector)

    await whatsapp.on_send_watchdog(
        Event(
            id=21,
            tenant_id=TENANT_A,
            event_type="whatsapp.send_watchdog",
            payload={"message_id": str(queued.id)},
            attempts=1,
            dedupe_key=f"send-watchdog:{queued.id}",
        )
    )

    row = await su.fetchrow("select status, error from messages where id=$1", queued.id)
    assert row is not None and row["status"] == "failed"
    assert json.loads(row["error"])["code"] == "delivery_unknown"
    assert connector.requests == []
