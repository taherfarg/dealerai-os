"""Short-lived links to private stored objects.

A browser cannot put an Authorization header on an `<img src>`, which is the only
reason signed links exist. Signing them ourselves works for both back ends — the
local disk and Supabase Storage — and keeps customer media private without
handing the browser a storage key.

The link is the capability: it names one object, expires within the hour, and is
signed under its own prefix, so a media link can never be replayed as a session
token or the other way round.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from datetime import timedelta

from ..config import get_settings
from ..core.security import AuthUnavailable, Unauthenticated

#: Domain separation: the same secret signs sessions.
_PREFIX = b"dealerai/media-link/v1:"
DEFAULT_TTL = timedelta(hours=1)


def _key() -> bytes:
    secret = get_settings().supabase_jwt_secret
    if not secret:
        raise AuthUnavailable("SUPABASE_JWT_SECRET is not set")
    return secret.encode()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(storage_path: str, *, expires_in: timedelta = DEFAULT_TTL) -> str:
    expiry = int(time.time() + expires_in.total_seconds())
    body = f"{expiry}:{storage_path}".encode()
    signature = hmac.new(_key(), _PREFIX + body, hashlib.sha256).digest()
    return f"{_b64(body)}.{_b64(signature)}"


def verify(token: str) -> str:
    """The storage path this link names, or Unauthenticated.

    Never says which check failed: expiry, signature and shape are one answer.
    """
    try:
        encoded_body, encoded_signature = token.split(".", 1)
        body = _unb64(encoded_body)
        signature = _unb64(encoded_signature)
    except (ValueError, binascii.Error) as exc:
        raise Unauthenticated("invalid media link") from exc

    expected = hmac.new(_key(), _PREFIX + body, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise Unauthenticated("invalid media link")

    try:
        expiry, _, storage_path = body.decode().partition(":")
        expired = int(expiry) < time.time()
    except (UnicodeDecodeError, ValueError) as exc:
        raise Unauthenticated("invalid media link") from exc
    if not storage_path or expired:
        raise Unauthenticated("invalid media link")
    return storage_path


def url_for(storage_path: str) -> str:
    """Where the browser fetches this object."""
    return f"/v1/media/{sign(storage_path)}"
