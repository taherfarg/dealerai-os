from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from dealerai.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


def test_env_example_covers_every_setting() -> None:
    """Cheaper and louder than generating .env.example: this fails the moment
    config.py and the example file drift apart."""
    documented = set(re.findall(r"^([A-Z_]+)=", ENV_EXAMPLE.read_text("utf-8"), re.M))
    declared = {name.upper() for name in Settings.model_fields}
    missing = declared - documented
    assert not missing, f"settings not documented in .env.example: {sorted(missing)}"

    unknown = documented - declared
    assert not unknown, (
        f".env.example declares variables config.py does not read: {sorted(unknown)}"
    )


def test_missing_required_setting_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)  # type: ignore[call-arg]
    assert "database_url" in str(exc.value).lower()


def test_migration_dsn_falls_back_to_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # _env_file=None only silences the file; pydantic-settings still reads the
    # process environment, and CI exports MIGRATION_DATABASE_URL as a job var.
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    s = Settings(_env_file=None, database_url="postgresql://x/y")  # type: ignore[call-arg]
    assert s.migration_dsn == "postgresql://x/y"


def test_http_clients_do_not_write_addresses_into_the_log() -> None:
    """httpx announces every request with its whole URL. A push subscription's
    endpoint is the address of somebody's phone, and it must not end up in a
    log because a worker sent to it."""
    import logging

    from dealerai.core.logging import configure_logging

    root = logging.getLogger()
    before = root.level
    root.setLevel(logging.DEBUG)  # as LOG_LEVEL=DEBUG does on a laptop
    try:
        configure_logging()
        for client in ("httpx", "httpcore"):
            assert not logging.getLogger(client).isEnabledFor(logging.INFO), client
    finally:
        root.setLevel(before)
