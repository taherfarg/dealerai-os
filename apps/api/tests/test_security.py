"""Whose token is it? (core/security.py)

A stand-in for a Supabase project: a key it signs with, and the address where
it publishes the public half. Nothing here opens a connection — `_download`,
the one function that leaves the machine, is replaced.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from dealerai.config import get_settings
from dealerai.core import security
from dealerai.core.security import (
    AuthUnavailable,
    Unauthenticated,
    decode_supabase_jwt,
    mint_test_token,
)

PROJECT = "https://abcdefghijklmnop.supabase.co"
USER = UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")


class Project:
    """As far as the API can tell, a Supabase project."""

    def __init__(self) -> None:
        self.downloads = 0
        self.down = False
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.kid = uuid4().hex

    def rotate(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.kid = uuid4().hex

    async def download(self, url: str) -> dict[str, Any]:
        assert url == f"{PROJECT}/auth/v1/.well-known/jwks.json"
        self.downloads += 1
        if self.down:
            raise httpx.ConnectError("the project cannot be reached")
        public = ECAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        return {"keys": [{**public, "kid": self.kid, "alg": "ES256", "use": "sig"}]}

    def claims(self, **changes: Any) -> dict[str, Any]:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": str(USER),
            "aud": "authenticated",
            "iss": f"{PROJECT}/auth/v1",
            "iat": now,
            "exp": now + 3600,
            "email": "layla@pollux.test",
            "role": "authenticated",
        }
        claims.update(changes)
        return {name: value for name, value in claims.items() if value is not None}

    def token(
        self,
        *,
        key: ec.EllipticCurvePrivateKey | None = None,
        kid: str | None = None,
        **changes: Any,
    ) -> str:
        return jwt.encode(
            self.claims(**changes),
            key or self.key,
            algorithm="ES256",
            headers={"kid": kid or self.kid},
        )


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch) -> Project:
    monkeypatch.setattr(get_settings(), "supabase_url", PROJECT)
    monkeypatch.setattr(security, "_keys", security._Keys({}, float("-inf")))
    it = Project()
    monkeypatch.setattr(security, "_download", it.download)
    return it


def aged(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """As if the keys had been fetched this long ago."""
    held = security._keys
    monkeypatch.setattr(security, "_keys", security._Keys(held.by_id, time.monotonic() - seconds))


def elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "env", "staging")


def hs256(claims: dict[str, Any], secret: bytes, **header: str) -> str:
    """Signed by hand: PyJWT, rightly, will not sign HS256 with a public key."""

    def part(value: dict[str, Any]) -> bytes:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=")

    body = part({"alg": "HS256", "typ": "JWT", **header}) + b"." + part(claims)
    signature = hmac.new(secret, body, hashlib.sha256).digest()
    return (body + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()


async def test_a_token_the_project_signed_is_accepted_and_its_keys_asked_for_once(
    project: Project,
) -> None:
    first = await decode_supabase_jwt(project.token())
    again = await decode_supabase_jwt(project.token(email="sara@pollux.test"))

    assert first.id == USER and first.email == "layla@pollux.test"
    assert again.email == "sara@pollux.test"
    assert project.downloads == 1


async def test_it_is_accepted_outside_a_laptop_which_is_the_point(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere(monkeypatch)
    assert (await decode_supabase_jwt(project.token())).id == USER


async def test_a_key_nobody_published_is_refused_and_asking_again_is_rationed(
    project: Project,
) -> None:
    for _ in range(3):
        with pytest.raises(Unauthenticated):
            await decode_supabase_jwt(project.token(kid="made-up"))
    # Anybody can send a token with a made-up key id: it buys one question a minute.
    assert project.downloads == 1


async def test_a_rotation_is_picked_up_without_a_restart(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    await decode_supabase_jwt(project.token())
    project.rotate()

    aged(monkeypatch, security.KEYS_RETRY + 1)
    assert (await decode_supabase_jwt(project.token())).id == USER
    assert project.downloads == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "anon"},
        {"iss": "https://somebody-else.supabase.co/auth/v1"},
        {"exp": int(time.time()) - 10},
        {"sub": None},
        {"sub": "not-a-user-id"},
    ],
    ids=["audience", "issuer", "expired", "no subject", "subject is not an id"],
)
async def test_a_token_that_is_not_a_users_is_refused(
    project: Project, changes: dict[str, Any]
) -> None:
    with pytest.raises(Unauthenticated):
        await decode_supabase_jwt(project.token(**changes))


async def test_somebody_elses_key_under_our_keys_id_is_refused(project: Project) -> None:
    forger = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(Unauthenticated):
        await decode_supabase_jwt(project.token(key=forger))


async def test_outside_a_laptop_a_shared_secret_token_is_refused(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = get_settings().supabase_jwt_secret
    assert secret
    ours = mint_test_token(USER, secret=secret, email="layla@pollux.test")
    # On a laptop this is how everybody signs in (routes/dev.py)…
    assert (await decode_supabase_jwt(ours)).id == USER

    # …and anywhere else, nothing this process holds may make a session.
    elsewhere(monkeypatch)
    with pytest.raises(Unauthenticated):
        await decode_supabase_jwt(ours)
    assert project.downloads == 0


async def test_the_public_key_is_not_a_shared_secret(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old trick: sign with HS256, using the key everybody can read."""
    published = project.key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    forged = hs256(project.claims(), published, kid=project.kid)

    with pytest.raises(Unauthenticated):
        await decode_supabase_jwt(forged)
    elsewhere(monkeypatch)
    with pytest.raises(Unauthenticated):
        await decode_supabase_jwt(forged)


@pytest.mark.parametrize("token", ["", "not a token", "a.b.c"])
async def test_what_is_not_a_token_is_refused(project: Project, token: str) -> None:
    with pytest.raises(Unauthenticated):
        await decode_supabase_jwt(token)


async def test_a_token_that_says_it_needs_no_signature_is_refused(project: Project) -> None:
    unsigned = jwt.encode(project.claims(), None, algorithm="none")  # type: ignore[arg-type]
    with pytest.raises(Unauthenticated):
        await decode_supabase_jwt(unsigned)


async def test_with_no_keys_and_no_way_to_get_them_it_is_a_503_not_a_401(
    project: Project,
) -> None:
    """A browser told 401 signs its user out. This is our outage, not their session."""
    project.down = True
    with pytest.raises(AuthUnavailable):
        await decode_supabase_jwt(project.token())


async def test_an_outage_keeps_the_keys_already_held(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    await decode_supabase_jwt(project.token())
    project.down = True

    aged(monkeypatch, security.KEYS_TTL + 1)
    assert (await decode_supabase_jwt(project.token())).id == USER
    assert project.downloads == 2, "it asked, was not answered, and carried on"


async def test_with_no_project_address_it_says_which_setting_is_missing(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "supabase_url", None)
    with pytest.raises(AuthUnavailable, match="SUPABASE_URL"):
        await decode_supabase_jwt(project.token())
