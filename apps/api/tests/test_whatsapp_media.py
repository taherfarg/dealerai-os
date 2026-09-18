"""WhatsApp media is downloaded once, stored privately, and audio is transcribed."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest

from conftest import TENANT_A
from dealerai.ai.transcription import Transcript
from dealerai.config import get_settings
from dealerai.connectors.base import ConnectorError
from dealerai.events.bus import Event
from dealerai.events.handlers import whatsapp

CHANNEL = UUID("aaaaaaaa-1111-4111-8111-111111111111")


class FakeConnector:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        self.calls += 1
        if self.error:
            raise self.error
        assert media_id == "media-1"
        return b"OggS voice", "audio/ogg; codecs=opus"


async def _message(su: asyncpg.Connection) -> UUID:
    await su.execute(
        """insert into channels (id, tenant_id, platform, external_id, account_id, mode)
           values ($1, $2, 'whatsapp', 'phone-1', 'waba-1', 'cloud_api')""",
        CHANNEL,
        TENANT_A,
    )
    contact_id = await su.fetchval(
        "insert into contacts (tenant_id, full_name) values ($1, 'Karim') returning id", TENANT_A
    )
    conversation_id = await su.fetchval(
        """insert into conversations (tenant_id, contact_id, channel_id, surface)
           values ($1, $2, $3, 'whatsapp') returning id""",
        TENANT_A,
        contact_id,
        CHANNEL,
    )
    message_id = await su.fetchval(
        """insert into messages
             (tenant_id, conversation_id, direction, sender, origin, type, external_id, media)
           values ($1, $2, 'in', 'customer', 'customer', 'audio', 'wamid.audio', $3)
           returning id""",
        TENANT_A,
        conversation_id,
        json.dumps(
            [
                {
                    "external_id": "media-1",
                    "mime": "audio/ogg; codecs=opus",
                    "filename": None,
                    "status": "pending",
                }
            ]
        ),
    )
    return UUID(str(message_id))


def _event(message_id: UUID, *, attempts: int = 1, max_attempts: int = 5) -> Event:
    return Event(
        id=11,
        tenant_id=TENANT_A,
        event_type="message.media_requested",
        payload={
            "message_id": str(message_id),
            "channel_id": str(CHANNEL),
            "media_id": "media-1",
            "mime": "audio/ogg; codecs=opus",
            "filename": None,
        },
        attempts=attempts,
        dedupe_key=f"media:{message_id}:media-1",
        max_attempts=max_attempts,
    )


@pytest.fixture
def local_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    monkeypatch.setattr(get_settings(), "env", "local")
    return tmp_path


async def test_media_is_downloaded_stored_and_audio_is_queued_for_transcription(
    db: None,
    su: asyncpg.Connection,
    seeded: None,
    local_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message_id = await _message(su)
    connector = FakeConnector()
    monkeypatch.setattr(whatsapp, "whatsapp_for_channel", lambda channel: connector)

    await whatsapp.on_media_requested(_event(message_id))

    media = json.loads(await su.fetchval("select media from messages where id=$1", message_id))[0]
    assert media["status"] == "ready"
    assert media["mime"] == "audio/ogg; codecs=opus"
    assert media["size"] == len(b"OggS voice")
    assert media["storage_path"].startswith(f"{TENANT_A}/messages/")
    assert (local_storage / media["storage_path"]).read_bytes() == b"OggS voice"
    [event] = await su.fetch(
        "select event_type, payload from events where event_type='message.transcription_requested'"
    )
    assert json.loads(event["payload"])["message_id"] == str(message_id)

    await whatsapp.on_media_requested(_event(message_id))
    assert connector.calls == 1


async def test_retryable_media_failure_stays_pending_until_the_last_attempt(
    db: None,
    su: asyncpg.Connection,
    seeded: None,
    local_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message_id = await _message(su)
    connector = FakeConnector(error=ConnectorError("network down"))
    monkeypatch.setattr(whatsapp, "whatsapp_for_channel", lambda channel: connector)

    with pytest.raises(ConnectorError, match="network down"):
        await whatsapp.on_media_requested(_event(message_id, attempts=1, max_attempts=2))
    pending = json.loads(await su.fetchval("select media from messages where id=$1", message_id))[0]
    assert pending["status"] == "pending"

    await whatsapp.on_media_requested(_event(message_id, attempts=2, max_attempts=2))
    failed = json.loads(await su.fetchval("select media from messages where id=$1", message_id))[0]
    assert failed["status"] == "failed"
    assert failed["error"] == "network down"


async def test_audio_transcription_is_stored_and_unblocks_the_reply_draft(
    db: None,
    su: asyncpg.Connection,
    seeded: None,
    local_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message_id = await _message(su)
    connector = FakeConnector()
    monkeypatch.setattr(whatsapp, "whatsapp_for_channel", lambda channel: connector)
    await whatsapp.on_media_requested(_event(message_id))

    async def fake_transcribe(*, tenant_id: UUID, data: bytes, mime: str) -> Transcript:
        assert tenant_id == TENANT_A
        assert data == b"OggS voice"
        assert mime == "audio/ogg; codecs=opus"
        return Transcript(text="Is the Hilux available?", language="en")

    monkeypatch.setattr(whatsapp, "transcribe_audio", fake_transcribe)
    await whatsapp.on_transcription_requested(
        Event(
            id=12,
            tenant_id=TENANT_A,
            event_type="message.transcription_requested",
            payload={"message_id": str(message_id), "media_id": "media-1"},
            attempts=1,
            dedupe_key=f"transcribe:{message_id}:media-1",
        )
    )

    transcript = json.loads(
        await su.fetchval("select transcript from messages where id=$1", message_id)
    )
    assert transcript == {"language": "en", "text": "Is the Hilux available?"}
    [draft] = await su.fetch(
        "select payload from events where event_type='copilot.draft_requested'"
    )
    assert json.loads(draft["payload"])["message_id"] == str(message_id)
