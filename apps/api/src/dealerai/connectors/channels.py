"""Build platform connectors from encrypted channel rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..config import get_settings
from .base import MessagingConnector, NotSupported, SocialConnector
from .crypto import CredentialsCorrupt, decrypt
from .mock import MockConnector, whatsapp_simulator
from .whatsapp import WhatsAppCloud

_local_mocks: dict[str, MessagingConnector] = {}
#: The local Instagram and Facebook, one per channel, for as long as the
#: process lives — what they published is what a test or a person looks at.
local_social: dict[str, MockConnector] = {}


def whatsapp_for_channel(channel: Mapping[str, Any]) -> MessagingConnector:
    stored = dict(channel.get("credentials") or {})
    settings = get_settings()
    if settings.is_local and stored.get("provider") == "mock":
        key = str(channel["external_id"])
        if key not in _local_mocks:
            _local_mocks[key] = whatsapp_simulator()
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


def social_for_channel(channel: Mapping[str, Any]) -> SocialConnector:
    """The connector a channel publishes through.

    ponytail: the local mock only. The Meta connector (T4.2) joins here, where
    its credentials are decrypted, and until then a real channel is refused
    with that reason rather than half-published.
    """
    stored = dict(channel.get("credentials") or {})
    if get_settings().is_local and stored.get("provider") == "mock":
        key = f"{channel['platform']}:{channel['external_id']}"
        return local_social.setdefault(key, MockConnector(platform=str(channel["platform"])))
    raise NotSupported(
        f"publishing to {channel['platform']} needs the Meta connector, which is not built yet"
    )
