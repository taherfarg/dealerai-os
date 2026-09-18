"""Local development keeps stored objects on disk, and nowhere else may."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from dealerai.config import get_settings
from dealerai.media import storage

TENANT = UUID("aaaaaaaa-0000-4000-8000-000000000001")


@pytest.fixture
def local_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    monkeypatch.setattr(get_settings(), "env", "local")
    return tmp_path


async def test_round_trip_on_disk(local_dir: Path) -> None:
    path = storage.object_path(TENANT, "messages", "ogg")
    assert await storage.upload(path, b"OggS voice", content_type="audio/ogg") == path
    assert (local_dir / path).read_bytes() == b"OggS voice"
    assert await storage.download(path) == b"OggS voice"


async def test_objects_are_never_overwritten(local_dir: Path) -> None:
    path = storage.object_path(TENANT, "messages", "ogg")
    await storage.upload(path, b"first", content_type="audio/ogg")
    with pytest.raises(storage.StorageUnavailable):
        await storage.upload(path, b"second", content_type="audio/ogg")


async def test_a_missing_object_is_not_found(local_dir: Path) -> None:
    with pytest.raises(storage.ObjectNotFound):
        await storage.download(f"{TENANT}/messages/2026/09/missing.ogg")


async def test_a_path_cannot_escape_the_directory(local_dir: Path) -> None:
    with pytest.raises(storage.ObjectNotFound):
        await storage.download("../../outside.txt")


async def test_disk_storage_is_refused_outside_local(
    local_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "env", "staging")
    with pytest.raises(storage.StorageUnavailable):
        await storage.upload("x/y.ogg", b"data", content_type="audio/ogg")


@pytest.mark.parametrize(
    ("mime", "filename", "expected"),
    [
        ("audio/ogg; codecs=opus", None, "ogg"),
        ("image/jpeg", None, "jpg"),
        ("application/pdf", "Invoice 2291.PDF", "pdf"),
        ("application/pdf", "no-extension", "pdf"),
        ("application/octet-stream", None, "bin"),
    ],
)
def test_extension_for(mime: str, filename: str | None, expected: str) -> None:
    assert storage.extension_for(mime, filename) == expected
