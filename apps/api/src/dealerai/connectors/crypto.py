"""Encryption for stored platform credentials.

`channels.credentials` holds OAuth tokens. RLS keeps one tenant from reading
another's, but a database dump, a backup, or a log of a bad query would expose
every dealer's Instagram and WhatsApp access at once. So the plaintext never
reaches Postgres.

Keys live in the secret manager, newest first in CREDENTIALS_KEYS. MultiFernet
decrypts with any of them and encrypts with the first, so rotation is: put a new
key at the front, redeploy, re-save each channel at leisure, drop the old key.

> ponytail: MultiFernet, not envelope encryption with per-record data keys.
> Envelope's payoff is re-wrapping small keys instead of re-encrypting large
> ciphertexts — these are 200-byte tokens, so it buys nothing and costs a key
> hierarchy to get wrong. Revisit if we ever store large per-tenant blobs.
"""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from ..config import get_settings
from ..core.errors import AppError

#: Bump when the payload layout changes so old rows stay readable.
VERSION = 1

_multi: MultiFernet | None = None


class CredentialsUnavailable(AppError):
    status = 503
    slug = "credentials-unavailable"
    title = "Credential encryption is not configured"


class CredentialsCorrupt(AppError):
    status = 500
    slug = "credentials-corrupt"
    title = "Stored credentials could not be decrypted"


def generate_key() -> str:
    """A fresh key, for `CREDENTIALS_KEYS`. Never generate one at runtime."""
    return Fernet.generate_key().decode()


def _fernet() -> MultiFernet:
    global _multi
    if _multi is None:
        raw = get_settings().credentials_keys
        if not raw:
            raise CredentialsUnavailable(
                "CREDENTIALS_KEYS is not set; generate one with "
                '`python -c "from dealerai.connectors.crypto import generate_key; '
                'print(generate_key())"`'
            )
        keys = [Fernet(k.strip().encode()) for k in raw.split(",") if k.strip()]
        if not keys:
            raise CredentialsUnavailable("CREDENTIALS_KEYS contained no usable keys")
        _multi = MultiFernet(keys)
    return _multi


def encrypt(credentials: dict[str, Any]) -> dict[str, Any]:
    """Wrap a credentials dict for storage in channels.credentials."""
    token = _fernet().encrypt(json.dumps(credentials, sort_keys=True).encode())
    return {"v": VERSION, "ct": token.decode()}


def decrypt(blob: dict[str, Any]) -> dict[str, Any]:
    if not blob:
        return {}
    if "ct" not in blob:
        raise CredentialsCorrupt("stored credentials are not in encrypted form")
    try:
        return dict(json.loads(_fernet().decrypt(blob["ct"].encode())))
    except InvalidToken as exc:
        raise CredentialsCorrupt(
            "no configured key could decrypt these credentials; "
            "was a key removed from CREDENTIALS_KEYS before rotation finished?"
        ) from exc


def rotate(blob: dict[str, Any]) -> dict[str, Any]:
    """Re-encrypt under the newest key without decrypting into application memory."""
    if "ct" not in blob:
        raise CredentialsCorrupt("stored credentials are not in encrypted form")
    try:
        return {"v": VERSION, "ct": _fernet().rotate(blob["ct"].encode()).decode()}
    except InvalidToken as exc:
        raise CredentialsCorrupt("cannot rotate credentials no configured key can read") from exc
