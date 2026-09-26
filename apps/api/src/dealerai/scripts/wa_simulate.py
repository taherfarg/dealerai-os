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
from ..connectors.mock import SIMULATOR_VOICE_MEDIA_ID
from .seed_sales import CUSTOMERS, PHONE_NUMBER_ID, WABA_ID

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
    phone: str | None = None,
    name: str = "Local Customer",
) -> dict[str, Any]:
    """`customer` is the business-scoped user id; `phone` is the wa_id.

    They are different fields on purpose: wa_id is a phone number, and Meta omits
    it for customers who use a username. Passing phone=None simulates that.
    """
    metadata = {
        "display_phone_number": "+971 50 000 0000",
        "phone_number_id": phone_number_id,
    }
    contact: dict[str, Any] = {
        "profile": {"name": name},
        "user_id": customer,
    }
    if phone:
        contact["wa_id"] = phone
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
            if phone:
                message["to"] = phone
        else:
            message["from_user_id"] = customer
            if phone:
                message["from"] = phone
            if kind == "voice":
                message["audio"] = {
                    "id": SIMULATOR_VOICE_MEDIA_ID,
                    "mime_type": "audio/ogg; codecs=opus",
                    "voice": True,
                }
            else:
                message["text"] = {"body": text}
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
        phone=None if args.no_phone else args.phone,
        name=args.name,
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
    parser.add_argument("--customer", default="AE.seed.1", help="business-scoped user id")
    parser.add_argument(
        "--phone",
        default=CUSTOMERS[0][1].removeprefix("+"),
        help="wa_id: the customer's number, digits only",
    )
    parser.add_argument(
        "--no-phone",
        action="store_true",
        help="omit wa_id, as Meta does for a customer with a username",
    )
    parser.add_argument(
        "--name",
        default=CUSTOMERS[0][0],
        help="WhatsApp profile name; it renames the customer unless a person edited theirs",
    )
    parser.add_argument("--text", default="Is the Hilux available?")
    parser.add_argument("--message-id")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
