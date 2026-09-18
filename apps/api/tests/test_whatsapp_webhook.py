"""WhatsApp webhook authentication, persistence, routing and fan-out."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import TENANT_A, reseed
from dealerai.config import get_settings
from dealerai.main import app

SECRET = "whatsapp-app-secret"
VERIFY_TOKEN = "verify-me"
PHONE_NUMBER_ID = "106540352242922"
WABA_ID = "102290129340398"


async def _prepare() -> None:
    await reseed()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute("delete from webhook_deliveries")
        await conn.execute("delete from events")
        await conn.execute(
            """insert into channels
                 (tenant_id, platform, external_id, account_id, mode, display_name)
               values ($1, 'whatsapp', $2, $3, 'cloud_api', 'Test WhatsApp')""",
            TENANT_A,
            PHONE_NUMBER_ID,
            WABA_ID,
        )
    finally:
        await conn.close()


async def _rows(query: str) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )
        return await conn.fetch(query)
    finally:
        await conn.close()


@pytest.fixture
def client(_migrated: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(get_settings(), "whatsapp_app_secret", SECRET)
    monkeypatch.setattr(get_settings(), "whatsapp_verify_token", VERIFY_TOKEN)
    asyncio.run(_prepare())
    with TestClient(app) as test_client:
        yield test_client


def _body(*, phone_number_id: str = PHONE_NUMBER_ID) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA_ID,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "+971 50 000 0101",
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Karim"},
                                    "wa_id": "971500000101",
                                    "user_id": "AE.13491208655302741918",
                                }
                            ],
                            "messages": [
                                {
                                    "from": "971500000101",
                                    "from_user_id": "AE.13491208655302741918",
                                    "id": "wamid.one",
                                    "timestamp": "1789646400",
                                    "text": {"body": "Is it available?"},
                                    "type": "text",
                                },
                                {
                                    "from_user_id": "AE.13491208655302741918",
                                    "id": "wamid.two",
                                    "timestamp": "1789646401",
                                    "audio": {"id": "media-1", "mime_type": "audio/ogg"},
                                    "type": "audio",
                                },
                            ],
                            "statuses": [
                                {
                                    "id": "wamid.out",
                                    "status": "delivered",
                                    "timestamp": "1789646402",
                                    "recipient_id": "971500000101",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _signed(body: dict[str, Any], *, secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body, separators=(",", ":")).encode()
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={digest}"}


def test_meta_challenge_needs_the_exact_verify_token(client: TestClient) -> None:
    accepted = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "42"},
    )
    assert accepted.status_code == 200
    assert accepted.text == "42"

    refused = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"},
    )
    assert refused.status_code == 401


@pytest.mark.parametrize("headers", [{}, {"X-Hub-Signature-256": "sha256=bad"}])
def test_an_unauthenticated_delivery_is_not_persisted(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.post("/webhooks/whatsapp", content=b"{}", headers=headers)
    assert response.status_code == 401
    assert asyncio.run(_rows("select id from webhook_deliveries")) == []


def test_a_valid_delivery_is_persisted_routed_and_split_into_events(client: TestClient) -> None:
    raw, headers = _signed(_body())
    response = client.post("/webhooks/whatsapp", content=raw, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "accepted"}

    [delivery] = asyncio.run(_rows("select tenant_id, signature_ok, body from webhook_deliveries"))
    assert delivery["tenant_id"] == TENANT_A
    assert delivery["signature_ok"] is True
    assert delivery["body"]["object"] == "whatsapp_business_account"

    events = asyncio.run(
        _rows(
            """select tenant_id, event_type, dedupe_key, priority, payload
               from events order by id"""
        )
    )
    assert [(e["event_type"], e["dedupe_key"], e["priority"]) for e in events] == [
        ("whatsapp.message_received", "wamid.one", 10),
        ("whatsapp.message_received", "wamid.two", 10),
        ("whatsapp.status_received", "wamid.out:delivered", 10),
    ]
    assert all(e["tenant_id"] == TENANT_A for e in events)
    assert all(e["payload"]["channel_id"] for e in events)
    assert events[0]["payload"]["contacts"][0]["user_id"].startswith("AE.")


def test_a_replayed_delivery_does_not_duplicate_events(client: TestClient) -> None:
    raw, headers = _signed(_body())
    assert client.post("/webhooks/whatsapp", content=raw, headers=headers).status_code == 200
    assert client.post("/webhooks/whatsapp", content=raw, headers=headers).status_code == 200
    [counts] = asyncio.run(
        _rows(
            """select (select count(*) from webhook_deliveries) as deliveries,
                      (select count(*) from events) as events"""
        )
    )
    assert (counts["deliveries"], counts["events"]) == (2, 3)


def test_an_unknown_number_is_kept_without_creating_an_unroutable_event(
    client: TestClient,
) -> None:
    raw, headers = _signed(_body(phone_number_id="unknown"))
    assert client.post("/webhooks/whatsapp", content=raw, headers=headers).status_code == 200
    [delivery] = asyncio.run(_rows("select tenant_id from webhook_deliveries"))
    assert delivery["tenant_id"] is None
    assert asyncio.run(_rows("select id from events")) == []
