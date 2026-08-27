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


def test_migration_dsn_falls_back_to_database_url() -> None:
    s = Settings(_env_file=None, database_url="postgresql://x/y")  # type: ignore[call-arg]
    assert s.migration_dsn == "postgresql://x/y"
