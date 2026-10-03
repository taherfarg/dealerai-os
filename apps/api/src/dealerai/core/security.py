"""JWT verification for the browser path.

A Supabase project signs its users' tokens with a private key and publishes the
public half at {SUPABASE_URL}/auth/v1/.well-known/jwks.json — ES256, or RS256 if
the project chose it. The API verifies them itself against a copy of those keys
rather than calling out to GoTrue on every request — a network hop per request,
on the critical path of every customer reply, to re-check a signature we can
check here.

HS256 under the shared secret is how this laptop signs (routes/dev.py, the
tests), and it is accepted only when ENV=local: anywhere else, nothing this
process holds may be enough to make somebody's session.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import jwt
import structlog

from ..config import get_settings
from .errors import AppError

log = structlog.get_logger()

#: How long a copy of the project's keys is trusted. Supabase's own edge keeps
#: the set for ten minutes, so asking sooner learns nothing.
KEYS_TTL = 600.0
#: How often a token naming a key we do not hold may send us back to ask. A
#: rotation looks like that — and so does anybody typing a made-up key id.
KEYS_RETRY = 60.0
ASYMMETRIC = ("ES256", "RS256")


class Unauthenticated(AppError):
    status = 401
    slug = "unauthenticated"
    title = "Missing or invalid credentials"


class AuthUnavailable(AppError):
    status = 503
    slug = "auth-unavailable"
    title = "Auth is not configured"


@dataclass(frozen=True, slots=True)
class AuthedUser:
    id: UUID
    email: str | None
    claims: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _Keys:
    by_id: dict[str, jwt.PyJWK]
    #: time.monotonic() when they were last asked for — answered or not.
    fetched_at: float


_keys = _Keys({}, float("-inf"))
_asking = asyncio.Lock()


def _issuer() -> str:
    url = get_settings().supabase_url
    if not url:
        raise AuthUnavailable("SUPABASE_URL is not set")
    return f"{url.rstrip('/')}/auth/v1"


async def _download(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(url)
    response.raise_for_status()
    body: dict[str, Any] = response.json()
    return body


async def _refresh() -> None:
    global _keys
    try:
        found = jwt.PyJWKSet.from_dict(await _download(f"{_issuer()}/.well-known/jwks.json"))
        _keys = _Keys({key.key_id: key for key in found.keys if key.key_id}, time.monotonic())
    except (httpx.HTTPError, jwt.PyJWKSetError, ValueError) as exc:
        # Keep what we hold: a project out of reach for a minute must not sign
        # everybody out. The time still moves on, so the next try is rationed.
        log.warning("signing_keys_unavailable", error=type(exc).__name__)
        _keys = _Keys(_keys.by_id, time.monotonic())


async def _signing_key(kid: str) -> jwt.PyJWK:
    age = time.monotonic() - _keys.fetched_at
    if age > KEYS_TTL or (kid not in _keys.by_id and age > KEYS_RETRY):
        async with _asking:
            # Whoever held the lock may have just asked.
            if time.monotonic() - _keys.fetched_at > KEYS_RETRY:
                await _refresh()
    if not _keys.by_id:
        # Our outage, not their session: a browser told 401 signs its user out.
        raise AuthUnavailable("the project's signing keys could not be read")
    key = _keys.by_id.get(kid)
    if key is None:
        raise Unauthenticated("invalid token")
    return key


async def decode_supabase_jwt(token: str) -> AuthedUser:
    settings = get_settings()
    checks: dict[str, Any] = {
        # Supabase sets aud="authenticated" on user tokens. Verifying it stops
        # an anon or service token being accepted as a user.
        "audience": "authenticated",
        "options": {"require": ["sub", "exp"]},
    }
    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        if algorithm == "HS256" and settings.is_local:
            if not settings.supabase_jwt_secret:
                raise AuthUnavailable("SUPABASE_JWT_SECRET is not set")
            claims = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], **checks)
        elif algorithm in ASYMMETRIC:
            issuer = _issuer()
            key = await _signing_key(str(header.get("kid", "")))
            # The key says how it signs, not the token: a token may claim any
            # algorithm it likes.
            claims = jwt.decode(
                token, key.key, algorithms=[key.algorithm_name], issuer=issuer, **checks
            )
        else:
            raise Unauthenticated("invalid token")
    except jwt.ExpiredSignatureError as exc:
        raise Unauthenticated("token has expired") from exc
    except jwt.InvalidTokenError as exc:
        # Deliberately vague to the caller: which check failed is a probing aid.
        raise Unauthenticated("invalid token") from exc

    try:
        user_id = UUID(str(claims["sub"]))
    except (KeyError, ValueError) as exc:
        raise Unauthenticated("token subject is not a user id") from exc

    return AuthedUser(id=user_id, email=claims.get("email"), claims=claims)


def mint_test_token(
    user_id: UUID,
    *,
    secret: str,
    email: str | None = None,
    name: str | None = None,
    expires_in_seconds: int = 3600,
) -> str:
    """Issue a token with Supabase's claim shape. Tests and local seeding only.

    Kept beside the verifier on purpose: if the claim shape drifts, both halves
    move together instead of the tests quietly asserting a shape production no
    longer sees.
    """
    import time

    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "aud": "authenticated",
        "role": "authenticated",
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    if email:
        payload["email"] = email
    if name:
        # Where Supabase puts what somebody typed on sign-up, and what Google
        # calls them.
        payload["user_metadata"] = {"full_name": name}
    return jwt.encode(payload, secret, algorithm="HS256")
