"""Build platform connectors from encrypted channel rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..config import get_settings
from .base import MessagingConnector
from .crypto import CredentialsCorrupt, decrypt
from .mock import whatsapp_like
from .whatsapp import WhatsAppCloud

_local_mocks: dict[str, MessagingConnector] = {}


def whatsapp_for_channel(channel: Mapping[str, Any]) -> MessagingConnector:
    stored = dict(channel.get("credentials") or {})
    settings = get_settings()
    if settings.is_local and stored.get("provider") == "mock":
        key = str(channel["external_id"])
        if key not in _local_mocks:
            connector = whatsapp_like()
            connector.media["local-media-1"] = (b"OggS local voice note", "audio/ogg")
            _local_mocks[key] = connector
        return _local_mocks[key]
    credentials = decrypt(stored)
    token = credentials.get("access_token")
    if not token:
        raise CredentialsCorrupt("WhatsApp channel has no access_token")
    return WhatsAppCloud(
        phone_number_id=str(channel["external_id"]),
        waba_id=str(channel["account_id"]) if channel.get("account_id") else None,
        access_token=str(token),
        graph_version=settings.whatsapp_graph_version,
    )
