"""Unauthenticated platform callbacks, authenticated by the platform signature."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from ..config import get_settings
from ..core.security import Unauthenticated
from ..db.session import system_session
from ..events.bus import emit

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@dataclass(frozen=True, slots=True)
class RoutedItem:
    event_type: str
    dedupe_key: str
    priority: int
    payload: dict[str, Any]


def _verified(raw: bytes, signature: str | None) -> bool:
    secret = get_settings().whatsapp_app_secret
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


def _items(field: str, value: dict[str, Any], channel_id: UUID) -> list[RoutedItem]:
    shared = {
        "channel_id": str(channel_id),
        "contacts": list(value.get("contacts") or []),
        "metadata": dict(value.get("metadata") or {}),
    }
    items: list[RoutedItem] = []
    if field == "messages":
        for message in value.get("messages") or []:
            message_id = str(message.get("id") or "")
            if message_id:
                items.append(
                    RoutedItem(
                        "whatsapp.message_received",
                        message_id,
                        10,
                        {**shared, "message": message},
                    )
                )
        for status in value.get("statuses") or []:
            message_id = str(status.get("id") or "")
            state = str(status.get("status") or "unknown")
            if message_id:
                items.append(
                    RoutedItem(
                        "whatsapp.status_received",
                        f"{message_id}:{state}",
                        10,
                        {**shared, "status": status},
                    )
                )
    elif field == "smb_message_echoes":
        for echo in value.get("messages") or value.get("message_echoes") or []:
            message_id = str(echo.get("id") or "")
            if message_id:
                items.append(
                    RoutedItem(
                        "whatsapp.echo_received",
                        message_id,
                        10,
                        {**shared, "message": echo},
                    )
                )
    elif field == "message_template_status_update":
        template_id = str(value.get("message_template_id") or value.get("id") or "unknown")
        event = str(value.get("event") or value.get("status") or "unknown")
        at = str(value.get("timestamp") or value.get("last_updated_time") or "")
        items.append(
            RoutedItem(
                "whatsapp.template_status",
                f"{template_id}:{event}:{at}",
                2,
                {**shared, "update": value},
            )
        )
    elif field == "user_id_update":
        raw_update = value.get("user_id")
        update: dict[str, Any] = raw_update if isinstance(raw_update, dict) else value
        previous = str(update.get("previous") or "")
        current = str(update.get("current") or "")
        if previous and current:
            items.append(
                RoutedItem(
                    "whatsapp.user_id_changed",
                    f"{previous}:{current}",
                    8,
                    {**shared, "update": update},
                )
            )
    return items


@router.get("/whatsapp", response_class=PlainTextResponse)
async def verify_whatsapp(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> str:
    settings = get_settings()
    if (
        mode != "subscribe"
        or not settings.whatsapp_verify_token
        or not hmac.compare_digest(token or "", settings.whatsapp_verify_token)
    ):
        raise Unauthenticated("invalid WhatsApp verification token")
    return challenge or ""


@router.post("/whatsapp")
async def receive_whatsapp(
    request: Request,
    signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict[str, str]:
    raw = await request.body()
    if not _verified(raw, signature):
        raise Unauthenticated("invalid WhatsApp webhook signature")
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook body")

    async with system_session() as conn, conn.transaction():
        delivery_id = await conn.fetchval(
            """insert into webhook_deliveries (platform, signature_ok, headers, body)
               values ('whatsapp', true, $1, $2) returning id""",
            dict(request.headers),
            body,
        )
        routed_tenants: set[UUID] = set()
        first_event_id: int | None = None
        for entry in body.get("entry") or []:
            account_id = str(entry.get("id") or "") or None
            for change in entry.get("changes") or []:
                field = str(change.get("field") or "")
                value = change.get("value")
                if not isinstance(value, dict):
                    continue
                metadata = value.get("metadata")
                phone_number_id = (
                    str(metadata.get("phone_number_id"))
                    if isinstance(metadata, dict) and metadata.get("phone_number_id")
                    else None
                )
                route = await conn.fetchrow(
                    "select tenant_id, channel_id from app.route_whatsapp($1, $2)",
                    phone_number_id,
                    account_id,
                )
                if route is None:
                    continue
                tenant_id = route["tenant_id"]
                routed_tenants.add(tenant_id)
                for item in _items(field, value, route["channel_id"]):
                    event_id = await emit(
                        conn,
                        item.event_type,
                        item.payload,
                        tenant_id=tenant_id,
                        dedupe_key=item.dedupe_key,
                        priority=item.priority,
                    )
                    first_event_id = first_event_id or event_id

        delivery_tenant = next(iter(routed_tenants)) if len(routed_tenants) == 1 else None
        await conn.execute(
            "update webhook_deliveries set tenant_id = $2, event_id = $3 where id = $1",
            delivery_id,
            delivery_tenant,
            first_event_id,
        )
    return {"status": "accepted"}
