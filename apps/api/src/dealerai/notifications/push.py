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
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

#: A push service must take 4096 octets and need not take more. Everything sent
#: here is one record, well inside it — message() sees to that.
RECORD_SIZE = 4096
#: A VAPID token's life. Push services refuse more than a day.
VAPID_SECONDS = 12 * 3600

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
