"""JWT verification for the browser path.

Supabase Auth issues HS256 tokens signed with the project's JWT secret. The API
verifies them itself rather than calling out to GoTrue on every request — a
network hop per request, on the critical path of every customer reply, to
re-check a signature we can check locally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt

from ..config import get_settings
from .errors import AppError


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


def decode_supabase_jwt(token: str) -> AuthedUser:
    secret = get_settings().supabase_jwt_secret
    if not secret:
        raise AuthUnavailable("SUPABASE_JWT_SECRET is not set")

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            # Supabase sets aud="authenticated" on user tokens. Verifying it
            # stops an anon or service token being accepted as a user.
            audience="authenticated",
            options={"require": ["sub", "exp"]},
        )
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
    return jwt.encode(payload, secret, algorithm="HS256")
