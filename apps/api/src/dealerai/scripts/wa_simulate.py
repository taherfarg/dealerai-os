"""Send a signed WhatsApp-shaped webhook to the local API."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import sys
import time
from typing import Any, Literal
from uuid import uuid4

import httpx

from ..config import get_settings
from .seed_sales import PHONE_NUMBER_ID, WABA_ID

Kind = Literal["inbound", "voice", "echo", "status"]


def build_payload(
    kind: Kind,
    *,
    phone_number_id: str,
    account_id: str,
    customer: str,
    text: str,
    message_id: str,
    timestamp: int,
) -> dict[str, Any]:
    metadata = {
        "display_phone_number": "+971 50 000 0000",
        "phone_number_id": phone_number_id,
    }
    contact = {
        "profile": {"name": "Local Customer"},
        "wa_id": customer,
        "user_id": customer,
    }
    if kind == "status":
        field = "messages"
        value: dict[str, Any] = {
            "metadata": metadata,
            "statuses": [{"id": message_id, "status": text, "timestamp": str(timestamp)}],
        }
    else:
        field = "smb_message_echoes" if kind == "echo" else "messages"
        message: dict[str, Any] = {
            "id": message_id,
            "timestamp": str(timestamp),
            "type": "audio" if kind == "voice" else "text",
        }
        if kind == "echo":
            message |= {"to_user_id": customer, "text": {"body": text}}
        elif kind == "voice":
            message |= {
                "from_user_id": customer,
                "audio": {"id": "local-media-1", "mime_type": "audio/ogg"},
            }
        else:
            message |= {"from_user_id": customer, "text": {"body": text}}
        value = {"metadata": metadata, "contacts": [contact], "messages": [message]}
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": account_id, "changes": [{"field": field, "value": value}]}],
    }


def signed_body(payload: dict[str, Any], secret: str) -> tuple[bytes, str]:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, f"sha256={digest}"


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.is_local:
        print(f"refusing to simulate: ENV is {settings.env!r}, expected 'local'", file=sys.stderr)
        return 1
    if not settings.whatsapp_app_secret:
        print("WHATSAPP_APP_SECRET is required", file=sys.stderr)
        return 1
    message_id = args.message_id or f"wamid.local.{uuid4().hex}"
    payload = build_payload(
        args.kind,
        phone_number_id=args.phone_number_id,
        account_id=args.account_id,
        customer=args.customer,
        text=args.text,
        message_id=message_id,
        timestamp=int(time.time()),
    )
    raw, signature = signed_body(payload, settings.whatsapp_app_secret)
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            args.url,
            content=raw,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
        )
    if not response.is_success:
        print(f"simulator failed ({response.status_code}): {response.text}", file=sys.stderr)
        return 1
    print(f"accepted {args.kind} webhook for {message_id}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a signed webhook to the local DealerAI API")
    parser.add_argument("kind", choices=("inbound", "voice", "echo", "status"))
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhooks/whatsapp")
    parser.add_argument("--phone-number-id", default=PHONE_NUMBER_ID)
    parser.add_argument("--account-id", default=WABA_ID)
    parser.add_argument("--customer", default="AE.seed.1")
    parser.add_argument("--text", default="Is the Hilux available?")
    parser.add_argument("--message-id")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
