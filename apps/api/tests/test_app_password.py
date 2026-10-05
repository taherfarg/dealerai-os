"""`npm run db:app-password:staging`: the application's way into a hosted database.

Tried here on the local database, with a role made for the test — never with
`dealerai_app`, whose local password everything else relies on.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest

from dealerai.config import get_settings
from dealerai.scripts import app_password


@pytest.fixture
async def role(su: asyncpg.Connection) -> AsyncIterator[str]:
    """A role that cannot sign in yet, as `dealerai_app` is on a new project."""
    name = f"dealerai_tmp_{uuid4().hex[:8]}"
    await su.execute(f'create role "{name}" nologin')
    try:
        yield name
    finally:
        await su.execute(f'drop role if exists "{name}"')


def test_what_is_sent_is_not_the_password() -> None:
    """`alter role … password 'x'` leaves x in the server's log. What goes
    instead is what the server would have stored anyway."""
    verifier = app_password.scram_verifier("correct horse battery staple")

    assert verifier.startswith("SCRAM-SHA-256$4096:")
    assert "correct" not in verifier and "staple" not in verifier
    # A salt of its own every time…
    assert verifier != app_password.scram_verifier("correct horse battery staple")
    # …and nothing else that varies.
    salt = b"sixteen bytes!!!"
    assert app_password.scram_verifier("x", salt=salt) == app_password.scram_verifier(
        "x", salt=salt
    )


def test_a_password_made_here_fits_in_an_address_as_it_is() -> None:
    made = {app_password.new_password() for _ in range(50)}
    assert len(made) == 50
    assert all(len(password) >= 40 and password.isalnum() for password in made)


@pytest.mark.parametrize(
    ("migration", "application"),
    [
        (
            "postgresql://postgres.abcdefgh:old%23pw@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres",
            "postgresql://dealerai_app.abcdefgh:NEW@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres",
        ),
        (
            "postgresql://postgres:old@db.abcdefgh.supabase.co:5432/postgres",
            "postgresql://dealerai_app:NEW@db.abcdefgh.supabase.co:5432/postgres",
        ),
    ],
    ids=["through the pooler, where a user carries the project", "direct"],
)
def test_the_applications_address_is_the_runners_with_its_own_user(
    migration: str, application: str
) -> None:
    assert app_password.address_for("dealerai_app", "NEW", migration) == application


async def test_the_role_can_sign_in_afterwards_and_only_with_what_was_made(role: str) -> None:
    dsn = get_settings().migration_dsn

    address = await app_password.give_password(dsn, role=role)

    conn = await asyncpg.connect(address)
    try:
        assert await conn.fetchval("select current_user") == role
    finally:
        await conn.close()

    parts = urlsplit(address)
    with pytest.raises(asyncpg.InvalidPasswordError):
        await asyncpg.connect(
            host=parts.hostname,
            port=parts.port,
            user=role,
            password="not what was made",
            database=parts.path.lstrip("/"),
        )


async def test_done_again_it_makes_another_and_the_old_one_stops_working(role: str) -> None:
    dsn = get_settings().migration_dsn
    first = await app_password.give_password(dsn, role=role)
    second = await app_password.give_password(dsn, role=role)

    assert first != second
    with pytest.raises(asyncpg.InvalidPasswordError):
        await asyncpg.connect(first)
    await (await asyncpg.connect(second)).close()


async def test_a_role_that_is_not_there_is_said_so(su: asyncpg.Connection) -> None:
    with pytest.raises(SystemExit, match="has the schema been applied"):
        await app_password.give_password(get_settings().migration_dsn, role="dealerai_nobody")


def test_it_will_not_put_a_secret_on_a_screen(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Asked for neither the clipboard nor a pipe, it changes nothing at all."""

    async def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("it went to the database before knowing where the secret would go")

    monkeypatch.setattr(get_settings(), "env", "staging")
    monkeypatch.setattr(app_password, "give_password", never)
    monkeypatch.setattr(app_password, "on_a_screen", lambda: True)

    assert app_password.main([]) == 2
    said = capsys.readouterr()
    assert "--clipboard" in said.err and said.out == ""


def test_it_is_not_for_a_laptop(capsys: pytest.CaptureFixture[str]) -> None:
    """Locally the migration runner sets the password everything expects."""
    assert app_password.main(["--clipboard"]) == 1
    assert "laptop" in capsys.readouterr().err


def test_down_a_pipe_it_is_one_line_a_host_can_import(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def give(dsn: str, *, role: str) -> str:
        assert role == "dealerai_app"
        return "postgresql://dealerai_app.abc:MADE@pooler:5432/postgres"

    monkeypatch.setattr(get_settings(), "env", "staging")
    monkeypatch.setattr(app_password, "give_password", give)
    monkeypatch.setattr(app_password, "on_a_screen", lambda: False)

    assert app_password.main([]) == 0
    said = capsys.readouterr()
    assert said.out == "DATABASE_URL=postgresql://dealerai_app.abc:MADE@pooler:5432/postgres\n"
    # What a person reads says that it happened, and not what it was.
    assert "MADE" not in said.err


def test_onto_the_clipboard_nothing_is_written_anywhere_else(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    copied: list[str] = []

    async def give(dsn: str, *, role: str) -> str:
        return "postgresql://dealerai_app.abc:MADE@pooler:5432/postgres"

    monkeypatch.setattr(get_settings(), "env", "staging")
    monkeypatch.setattr(app_password, "give_password", give)
    monkeypatch.setattr(app_password, "to_clipboard", copied.append)

    assert app_password.main(["--clipboard"]) == 0
    said = capsys.readouterr()
    assert copied == ["postgresql://dealerai_app.abc:MADE@pooler:5432/postgres"]
    assert said.out == "" and "MADE" not in said.err and "clipboard" in said.err
