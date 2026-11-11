"""The migration runner makes the database it is pointed at — on a laptop, and nowhere else."""

from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest

from dealerai.config import get_settings
from dealerai.scripts import migrate


async def test_create_makes_the_database_a_dsn_names_and_only_once(su: asyncpg.Connection) -> None:
    name = f"dealerai_tmp_{uuid4().hex[:8]}"
    dsn = f"{get_settings().migration_dsn.rsplit('/', 1)[0]}/{name}"
    try:
        await migrate.ensure_database(dsn)
        await migrate.ensure_database(dsn)  # there already: nothing to do, and no error
        assert await su.fetchval("select count(*) from pg_database where datname = $1", name) == 1
    finally:
        await su.execute(f'drop database if exists "{name}"')


async def test_create_is_refused_anywhere_but_a_laptop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(get_settings(), "env", "staging")
    assert await migrate.run(create=True) == 1
    assert "refusing" in capsys.readouterr().out
