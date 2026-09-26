"""Approved WhatsApp templates are synchronized and updated by webhook status."""

from __future__ import annotations

import json
from uuid import UUID

import asyncpg
import pytest

from conftest import TENANT_A, USER_A
from dealerai.connectors.base import TemplateInfo
from dealerai.core.security import AuthedUser
from dealerai.deps import TenantContext
from dealerai.events.bus import Event
from dealerai.events.handlers import whatsapp
from dealerai.routes.channels import list_templates, sync_templates

CHANNEL = UUID("aaaaaaaa-1111-4111-8111-111111111111")


class FakeConnector:
    async def list_templates(self) -> list[TemplateInfo]:
        return [
            TemplateInfo(
                external_id="meta-template-1",
                name="vehicle_available",
                language="en_US",
                category="utility",
                status="approved",
                components=[{"type": "BODY", "text": "The {{1}} is available at {{2}}."}],
            )
        ]


def _ctx() -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_A,
        user=AuthedUser(id=USER_A, email="alpha@example.test", claims={}),
        role="owner",
    )


async def _channel(su: asyncpg.Connection) -> None:
    await su.execute(
        """insert into channels (id, tenant_id, platform, external_id, account_id, mode)
           values ($1, $2, 'whatsapp', 'phone-1', 'waba-1', 'cloud_api')""",
        CHANNEL,
        TENANT_A,
    )


async def test_sync_request_is_idempotent_and_the_worker_upserts_templates(
    db: None,
    su: asyncpg.Connection,
    seeded: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _channel(su)
    accepted = await sync_templates(CHANNEL, _ctx())
    replay = await sync_templates(CHANNEL, _ctx())
    assert accepted == replay == {"status": "queued"}
    [queued] = await su.fetch("select event_type, payload from events")
    assert queued["event_type"] == "whatsapp.templates_sync_requested"

    monkeypatch.setattr(whatsapp, "whatsapp_for_channel", lambda channel: FakeConnector())
    await whatsapp.on_templates_sync_requested(
        Event(
            id=30,
            tenant_id=TENANT_A,
            event_type="whatsapp.templates_sync_requested",
            payload={"channel_id": str(CHANNEL)},
            attempts=1,
            dedupe_key=f"template-sync:{CHANNEL}",
        )
    )

    templates = await list_templates(CHANNEL, _ctx())
    assert len(templates) == 1
    assert templates[0].name == "vehicle_available"
    assert templates[0].body == "The {{1}} is available at {{2}}."
    assert templates[0].variables == ["1", "2"]


async def test_rejected_template_webhook_updates_the_row_and_notifies(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await _channel(su)
    await su.execute(
        """insert into message_templates
             (tenant_id, channel_id, external_id, name, language, category, status)
           values ($1, $2, 'meta-template-1', 'vehicle_available',
                   'en_US', 'utility', 'approved')""",
        TENANT_A,
        CHANNEL,
    )
    await whatsapp.on_template_status(
        Event(
            id=31,
            tenant_id=TENANT_A,
            event_type="whatsapp.template_status",
            payload={
                "channel_id": str(CHANNEL),
                "update": {
                    "message_template_id": "meta-template-1",
                    "event": "REJECTED",
                    "reason": "INCORRECT_CATEGORY",
                },
            },
            attempts=1,
            dedupe_key="meta-template-1:REJECTED:1",
        )
    )
    row = await su.fetchrow(
        "select status, rejected_reason from message_templates where external_id='meta-template-1'"
    )
    assert row is not None and (row["status"], row["rejected_reason"]) == (
        "rejected",
        "INCORRECT_CATEGORY",
    )
    [event] = await su.fetch(
        "select event_type, payload from events where event_type='notification.requested'"
    )
    assert json.loads(event["payload"])["kind"] == "template_rejected"
