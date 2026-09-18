"""Build platform connectors from encrypted channel rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..config import get_settings
from .crypto import CredentialsCorrupt, decrypt
from .whatsapp import WhatsAppCloud


def whatsapp_for_channel(channel: Mapping[str, Any]) -> WhatsAppCloud:
    credentials = decrypt(dict(channel.get("credentials") or {}))
    token = credentials.get("access_token")
    if not token:
        raise CredentialsCorrupt("WhatsApp channel has no access_token")
    return WhatsAppCloud(
        phone_number_id=str(channel["external_id"]),
        waba_id=str(channel["account_id"]) if channel.get("account_id") else None,
        access_token=str(token),
        graph_version=get_settings().whatsapp_graph_version,
    )
