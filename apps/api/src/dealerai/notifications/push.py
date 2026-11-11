"""Web Push, from the worker (docs/sales/07-frontend.md § 8).

Two standards over two libraries the API already has, rather than a push
library: the payload is encrypted per RFC 8291 (aes128gcm) with `cryptography`,
and the request is signed per RFC 8292 (VAPID) with PyJWT.
tests/test_push_crypto.py checks the first against the RFC's own worked
example, byte for byte.
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
import httpx
import jwt
import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

log = structlog.get_logger()

#: A push service must take 4096 octets and need not take more. Everything sent
#: here is one record, well inside it — message() sees to that.
RECORD_SIZE = 4096
#: A VAPID token's life. Push services refuse more than a day.
VAPID_SECONDS = 12 * 3600
#: How long a push service keeps trying a phone that is off. An hour: "a
#: customer is waiting" from this morning is not news this afternoon.
TTL_SECONDS = 3600

#: The push services browsers use. The worker POSTs to a subscription's
#: endpoint, so an address that is none of these is refused when it is offered:
#: nobody gets to aim the worker at a host of their choosing.
PUSH_SERVICES = (
    "fcm.googleapis.com",  # Chrome, and every browser on Android
    "updates.push.services.mozilla.com",  # Firefox
    "web.push.apple.com",  # Safari, and every browser on an iPhone
    "notify.windows.com",  # Edge on Windows
)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def is_push_service(endpoint: str) -> bool:
    try:
        target = urlsplit(endpoint)
        host = target.hostname or ""
    except ValueError:
        return False
    return target.scheme == "https" and any(
        host == known or host.endswith(f".{known}") for known in PUSH_SERVICES
    )


def private_key(scalar: str) -> ec.EllipticCurvePrivateKey:
    """A P-256 key from its base64url scalar — the form VAPID_PRIVATE_KEY takes."""
    return ec.derive_private_key(int.from_bytes(unb64(scalar), "big"), ec.SECP256R1())


def _point(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)


def public_key(scalar: str) -> str:
    """What the browser subscribes with: the uncompressed point, base64url."""
    return b64(_point(private_key(scalar)))


def hkdf(*, salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(
    plaintext: bytes,
    *,
    p256dh: str,
    auth: str,
    salt: bytes | None = None,
    server_key: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """RFC 8291: one aes128gcm record only this subscription can open.

    `salt` and `server_key` are fresh for every message; they are parameters so
    the RFC's example, which fixes both, can be reproduced.
    """
    ua_public = unb64(p256dh)
    salt = salt or os.urandom(16)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _point(server_key)

    shared = server_key.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    )
    ikm = hkdf(
        salt=unb64(auth),
        ikm=shared,
        info=b"WebPush: info\x00" + ua_public + as_public,
        length=32,
    )
    key = hkdf(salt=salt, ikm=ikm, info=b"Content-Encoding: aes128gcm\x00", length=16)
    nonce = hkdf(salt=salt, ikm=ikm, info=b"Content-Encoding: nonce\x00", length=12)
    # 0x02 ends the last — here the only — record.
    ciphertext = AESGCM(key).encrypt(nonce, plaintext + b"\x02", None)
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + ciphertext


def vapid(endpoint: str, *, private: str, subject: str) -> str:
    """RFC 8292: who is sending, signed for the push service it is sent to."""
    target = urlsplit(endpoint)
    now = int(time.time())
    token = jwt.encode(
        {
            "aud": f"{target.scheme}://{target.netloc}",
            "iat": now,
            "exp": now + VAPID_SECONDS,
            "sub": subject,
        },
        private_key(private),
        algorithm="ES256",
    )
    return f"vapid t={token}, k={public_key(private)}"


def message(title: str, body: str | None, *, href: str, tag: str) -> bytes:
    """What the service worker shows (apps/web/public/sw.js reads these names).

    Cut to what a lock screen shows anyway, which also keeps every message
    inside the one record encrypt() writes.
    """
    return json.dumps(
        {"title": title[:120], "body": (body or "")[:300], "href": href, "tag": tag},
        ensure_ascii=False,
    ).encode()


def client() -> httpx.AsyncClient:
    """Its own function so a test can hand the sender a push service of its own."""
    return httpx.AsyncClient(timeout=10)


async def send(
    http: httpx.AsyncClient,
    device: Mapping[str, Any],
    payload: bytes,
    *,
    private: str,
    subject: str,
) -> int:
    """One push to one device: the push service's status, or 0 when it could
    not be reached."""
    try:
        response = await http.post(
            device["endpoint"],
            content=encrypt(payload, p256dh=device["p256dh"], auth=device["auth"]),
            headers={
                "Authorization": vapid(device["endpoint"], private=private, subject=subject),
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(TTL_SECONDS),
                "Urgency": "high",
            },
        )
    except httpx.HTTPError as exc:
        log.warning("push_unreachable", because=type(exc).__name__)
        return 0
    return response.status_code


async def deliver(
    devices: Sequence[Mapping[str, Any]], payload: bytes, *, private: str, subject: str
) -> dict[UUID, int]:
    """The payload to each device, and what each push service answered. No
    database connection is held while this waits on the network."""
    async with client() as http:
        return {
            device["id"]: await send(http, device, payload, private=private, subject=subject)
            for device in devices
        }


def delivered(status: int) -> bool:
    return 200 <= status < 300


async def record(conn: asyncpg.Connection, answers: Mapping[UUID, int]) -> None:
    """What an answer means for the device (docs/sales/02-data-model.md § 4):
    one that is gone is forgotten, one that was reached is remembered, and
    anything else is only counted — a push service has bad days too."""
    for device_id, status in answers.items():
        if status in (404, 410):
            await conn.execute("delete from push_subscriptions where id = $1", device_id)
        elif delivered(status):
            await conn.execute(
                """update push_subscriptions
                      set last_success_at = now(), failure_count = 0 where id = $1""",
                device_id,
            )
        else:
            await conn.execute(
                "update push_subscriptions set failure_count = failure_count + 1 where id = $1",
                device_id,
            )
