"""Local-only sign-in as a seeded person."""

from __future__ import annotations

from types import SimpleNamespace

import asyncpg
import pytest

from dealerai.core.errors import NotFound
from dealerai.core.security import decode_supabase_jwt
from dealerai.routes import dev
from dealerai.scripts.seed_sales import PEOPLE, TENANT_SLUG, person_email, person_id


async def test_a_dev_session_is_a_token_the_api_accepts() -> None:
    name = PEOPLE[2][0]  # Ahmed, a salesperson
    session = await dev.create_session(dev.DevSessionIn(email=person_email(name)))
    user = await decode_supabase_jwt(session.access_token)
    assert user.id == person_id(name)
    assert session.tenant_slug == TENANT_SLUG


async def test_people_are_listed_with_their_roles() -> None:
    people = await dev.list_people()
    assert [(p.name, p.role) for p in people] == [(name, role) for name, role, *_ in PEOPLE]


async def test_somebody_new_gets_a_session_and_no_workspace(
    db: None, su: asyncpg.Connection
) -> None:
    """What Supabase does on sign-up, so an invitation can be accepted locally."""
    session = await dev.create_session(
        dev.DevSessionIn(email="Layla@Pollux.test", name="Layla Hassan")
    )
    user = await decode_supabase_jwt(session.access_token)
    assert user.email == "layla@pollux.test"
    assert user.claims["user_metadata"] == {"full_name": "Layla Hassan"}
    assert (session.tenant_id, session.tenant_slug) == (None, None)
    assert await su.fetchval("select email from auth.users where id = $1", user.id) == (
        "layla@pollux.test"
    )
    again = await dev.create_session(dev.DevSessionIn(email="layla@pollux.test"))
    assert (await decode_supabase_jwt(again.access_token)).id == user.id, "one person, one id"


@pytest.mark.parametrize("env", ["staging", "production"])
async def test_outside_local_the_routes_do_not_exist(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setattr(
        dev, "get_settings", lambda: SimpleNamespace(env=env, supabase_jwt_secret="x" * 40)
    )
    with pytest.raises(NotFound):
        await dev.list_people()
    with pytest.raises(NotFound):
        await dev.create_session(dev.DevSessionIn(email=person_email(PEOPLE[0][0])))


def test_the_router_is_not_registered_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second lock: a non-local app never mounts the routes at all."""
    from dealerai import main
    from dealerai.config import get_settings

    monkeypatch.setattr(get_settings(), "env", "staging")
    paths = {getattr(route, "path", "") for route in main.create_app().routes}
    assert not any(path.startswith("/internal/dev") for path in paths)


async def test_a_missing_jwt_secret_is_named_rather_than_signing_with_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dealerai.core.security import AuthUnavailable

    monkeypatch.setattr(
        dev, "get_settings", lambda: SimpleNamespace(env="local", supabase_jwt_secret=None)
    )
    with pytest.raises(AuthUnavailable):
        await dev.create_session(dev.DevSessionIn(email=person_email(PEOPLE[0][0])))
