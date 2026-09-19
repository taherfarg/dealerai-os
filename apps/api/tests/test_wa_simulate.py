"""The local simulator: the payloads it builds, and the path they actually take."""

from __future__ import annotations

import asyncio
import hashlib
import hmac

import asyncpg
import pytest
from fastapi.testclient import TestClient

from dealerai.config import get_settings
from dealerai.db import session
from dealerai.events.worker import Worker
from dealerai.main import app
from dealerai.scripts.seed_sales import CUSTOMERS, PHONE_NUMBER_ID, WABA_ID, seed
from dealerai.scripts.wa_simulate import build_payload, signed_body

SECRET = "simulator-app-secret"
PHONE = CUSTOMERS[0][1].removeprefix("+")


def test_inbound_payload_and_signature_match_the_real_webhook_shape() -> None:
    payload = build_payload(
        "inbound",
        phone_number_id="phone-1",
        account_id="waba-1",
        customer="AE.seed.1",
        phone=PHONE,
        text="Is it available?",
        message_id="wamid.local.1",
        timestamp=1_789_646_400,
    )
    change = payload["entry"][0]["changes"][0]
    assert change["field"] == "messages"
    message = change["value"]["messages"][0]
    contact = change["value"]["contacts"][0]
    # wa_id is a phone number and user_id is the BSUID: two different fields.
    assert (message["from_user_id"], message["from"]) == ("AE.seed.1", PHONE)
    assert (contact["user_id"], contact["wa_id"]) == ("AE.seed.1", PHONE)
    raw, signature = signed_body(payload, "secret")
    assert signature == "sha256=" + hmac.new(b"secret", raw, hashlib.sha256).hexdigest()


def test_a_customer_with_a_username_arrives_without_a_phone_number() -> None:
    payload = build_payload(
        "inbound",
        phone_number_id="phone-1",
        account_id="waba-1",
        customer="AE.seed.1",
        phone=None,
        text="Is it available?",
        message_id="wamid.local.1",
        timestamp=1,
    )
    value = payload["entry"][0]["changes"][0]["value"]
    assert "from" not in value["messages"][0]
    assert "wa_id" not in value["contacts"][0]


def test_voice_and_echo_use_their_platform_specific_shapes() -> None:
    voice = build_payload(
        "voice",
        phone_number_id="phone-1",
        account_id="waba-1",
        customer="AE.seed.1",
        phone=PHONE,
        text="hello",
        message_id="wamid.local.2",
        timestamp=1,
    )
    echo = build_payload(
        "echo",
        phone_number_id="phone-1",
        account_id="waba-1",
        customer="AE.seed.1",
        phone=PHONE,
        text="hello",
        message_id="wamid.local.3",
        timestamp=1,
    )
    audio = voice["entry"][0]["changes"][0]["value"]["messages"][0]
    assert audio["type"] == "audio"
    assert audio["audio"]["mime_type"] == "audio/ogg; codecs=opus"
    assert echo["entry"][0]["changes"][0]["field"] == "smb_message_echoes"
    assert echo["entry"][0]["changes"][0]["value"]["messages"][0]["to_user_id"] == "AE.seed.1"


async def _drain_then_read(external_id: str) -> asyncpg.Record | None:
    """The TestClient's lifespan closed the pool; the worker needs its own."""
    await session.init_pool()
    try:
        await Worker("simulator-test").run_once()
    finally:
        await session.close_pool()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return await conn.fetchrow(
            """select m.body, m.type, m.origin, c.full_name
               from messages m join conversations cv on cv.id = m.conversation_id
               join contacts c on c.id = cv.contact_id
               where m.external_id = $1""",
            external_id,
        )
    finally:
        await conn.close()


def test_the_default_inbound_payload_becomes_a_message(
    _migrated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`npm run wa:simulate inbound`, end to end.

    The shape tests above all passed while this path was broken: the simulator
    sent the BSUID as wa_id, and every simulated message died in the worker.
    """
    monkeypatch.setattr(get_settings(), "whatsapp_app_secret", SECRET)
    assert asyncio.run(seed()) == 0
    payload = build_payload(
        "inbound",
        phone_number_id=PHONE_NUMBER_ID,
        account_id=WABA_ID,
        customer="AE.seed.1",
        phone=PHONE,
        text="Is the Hilux available?",
        message_id="wamid.simulated.1",
        timestamp=1_789_646_400,
        name=CUSTOMERS[0][0],
    )
    raw, signature = signed_body(payload, SECRET)

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/whatsapp",
            content=raw,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
        )
    assert response.status_code == 200, response.text

    stored = asyncio.run(_drain_then_read("wamid.simulated.1"))
    assert stored is not None, "the simulated message never reached the inbox"
    assert stored["body"] == "Is the Hilux available?"
    assert stored["origin"] == "customer"
    # AE.seed.1 belongs to the first seeded customer, so it resolves to them.
    assert stored["full_name"] == CUSTOMERS[0][0]
