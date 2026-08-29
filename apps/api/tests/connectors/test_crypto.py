from __future__ import annotations

import json

import asyncpg
import pytest
from cryptography.fernet import Fernet, MultiFernet

from conftest import TENANT_A
from dealerai.connectors import crypto
from dealerai.connectors.crypto import CredentialsCorrupt, decrypt, encrypt

TOKEN = "EAAG-super-secret-instagram-token-9f2c"
CREDS = {"access_token": TOKEN, "expires_at": "2027-01-01T00:00:00Z"}


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> Fernet:
    key = Fernet(Fernet.generate_key())
    monkeypatch.setattr(crypto, "_multi", MultiFernet([key]))
    return key


def test_round_trip(keyed: Fernet) -> None:
    assert decrypt(encrypt(CREDS)) == CREDS


def test_ciphertext_does_not_contain_the_token(keyed: Fernet) -> None:
    blob = encrypt(CREDS)
    assert TOKEN not in json.dumps(blob)
    assert blob["v"] == crypto.VERSION


def test_output_is_json_serialisable_for_jsonb(keyed: Fernet) -> None:
    json.dumps(encrypt(CREDS))


def test_empty_blob_decrypts_to_empty(keyed: Fernet) -> None:
    assert decrypt({}) == {}


def test_plaintext_row_is_rejected_not_silently_returned(keyed: Fernet) -> None:
    """A row written before encryption existed must fail loudly, not leak."""
    with pytest.raises(CredentialsCorrupt):
        decrypt({"access_token": TOKEN})


def test_wrong_key_raises_rather_than_returning_garbage(
    keyed: Fernet, monkeypatch: pytest.MonkeyPatch
) -> None:
    blob = encrypt(CREDS)
    monkeypatch.setattr(crypto, "_multi", MultiFernet([Fernet(Fernet.generate_key())]))
    with pytest.raises(CredentialsCorrupt):
        decrypt(blob)


def test_rotation_reads_old_keys_and_writes_the_new_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old, new = Fernet(Fernet.generate_key()), Fernet(Fernet.generate_key())

    monkeypatch.setattr(crypto, "_multi", MultiFernet([old]))
    blob = encrypt(CREDS)

    # Newest first: decrypt still works during the overlap window.
    monkeypatch.setattr(crypto, "_multi", MultiFernet([new, old]))
    assert decrypt(blob) == CREDS

    rotated = crypto.rotate(blob)
    assert rotated["ct"] != blob["ct"]

    # Once rotated, the old key can be dropped.
    monkeypatch.setattr(crypto, "_multi", MultiFernet([new]))
    assert decrypt(rotated) == CREDS


async def test_stored_credentials_are_unreadable_in_the_database(
    db: None, seeded: None, keyed: Fernet, su: asyncpg.Connection
) -> None:
    """The acceptance criterion: a database dump must not expose a token."""
    from dealerai.db.session import tenant_session

    async with tenant_session(TENANT_A) as conn:
        await conn.execute(
            """insert into channels (tenant_id, platform, external_id, credentials)
               values ($1, 'instagram', 'ig_1', $2)""",
            TENANT_A,
            encrypt(CREDS),
        )

    raw = await su.fetchval("select credentials::text from channels where external_id = 'ig_1'")
    assert TOKEN not in raw, "the access token is sitting in plaintext in Postgres"

    async with tenant_session(TENANT_A) as conn:
        stored = await conn.fetchval("select credentials from channels where external_id = 'ig_1'")
    assert decrypt(stored)["access_token"] == TOKEN
