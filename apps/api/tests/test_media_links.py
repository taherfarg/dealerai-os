"""A link to one object, for one hour, for whoever holds it — and nothing else."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dealerai.config import get_settings
from dealerai.core.security import Unauthenticated
from dealerai.main import app
from dealerai.media.links import sign, url_for, verify

PATH = "11111111-0000-4000-8000-000000000001/messages/2026/09/abc.ogg"


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", "s" * 40)


def test_a_link_round_trips() -> None:
    assert verify(sign(PATH)) == PATH
    assert url_for(PATH).startswith("/v1/media/")


def test_an_expired_link_is_refused() -> None:
    with pytest.raises(Unauthenticated):
        verify(sign(PATH, expires_in=timedelta(seconds=-1)))


def test_a_link_cannot_be_pointed_at_another_object() -> None:
    body, signature = sign(PATH).split(".")
    tampered = sign(PATH.replace("abc", "xyz")).split(".")[0]
    with pytest.raises(Unauthenticated):
        verify(f"{tampered}.{signature}")
    assert body != tampered


def test_a_link_signed_with_another_key_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    token = sign(PATH)
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", "d" * 40)
    with pytest.raises(Unauthenticated):
        verify(token)


def test_nonsense_is_refused_without_saying_why() -> None:
    for token in ("not-a-link", "", "a.b", "...."):
        with pytest.raises(Unauthenticated) as exc:
            verify(token)
        assert "invalid media link" in str(exc.value)


def test_the_route_serves_the_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    target = tmp_path / PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"OggS voice")

    with TestClient(app) as client:
        ok = client.get(url_for(PATH))
        assert ok.status_code == 200
        assert ok.content == b"OggS voice"
        assert ok.headers["cache-control"].startswith("private")
        assert client.get("/v1/media/not-a-link").status_code == 401
        # A link to an object that is not there is not a link to someone else's.
        assert client.get(url_for("someone/else/missing.ogg")).status_code == 404
