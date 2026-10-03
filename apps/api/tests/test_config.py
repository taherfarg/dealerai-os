from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from dealerai.config import LOCAL_JWT_SECRET, Settings

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


def staging(**changes: object) -> Settings:
    """A configuration fit to serve, with one thing changed."""
    fit: dict[str, object] = {
        "env": "staging",
        "database_url": "postgresql://dealerai_app:secret@aws-0-ap-south-1.pooler.supabase.com:5432/postgres",
        "supabase_url": "https://abcdefghijklmnop.supabase.co",
        "supabase_jwt_secret": "a-secret-of-this-deployment-and-no-other",
        "web_origins": "https://staging.dealerai.example",
        "storage_dir": None,
        "vapid_private_key": None,
        "vapid_subject": "mailto:push@dealerai.local",
    }
    return Settings(_env_file=None, **{**fit, **changes})  # type: ignore[arg-type]


def test_a_laptop_has_nothing_to_answer_for() -> None:
    laptop = Settings(_env_file=None, env="local", database_url="postgresql://x/y")  # type: ignore[call-arg]
    assert laptop.deploy_problems() == []


def test_a_deployment_fit_to_serve_has_no_problems() -> None:
    # Including the placeholder push subject: with no push key, nothing is pushed.
    assert staging().deploy_problems() == []
    assert staging(env="production").deploy_problems() == []


@pytest.mark.parametrize(
    ("changes", "variable"),
    [
        ({"supabase_url": None}, "SUPABASE_URL"),
        ({"supabase_jwt_secret": None}, "SUPABASE_JWT_SECRET"),
        ({"supabase_jwt_secret": "too-short"}, "SUPABASE_JWT_SECRET"),
        ({"supabase_jwt_secret": LOCAL_JWT_SECRET}, "SUPABASE_JWT_SECRET"),
        ({"web_origins": "http://localhost:3000"}, "WEB_ORIGINS"),
        ({"storage_dir": ".storage"}, "STORAGE_DIR"),
        (
            {"database_url": "postgresql://dealerai_app:secret@pooler.supabase.com:6543/postgres"},
            "DATABASE_URL",
        ),
        ({"vapid_private_key": "a-key"}, "VAPID_SUBJECT"),
    ],
    ids=[
        "no project",
        "no secret",
        "a short secret",
        "the secret in the Supabase CLI's documentation",
        "localhost as the web app",
        "a laptop's storage",
        "the transaction pooler",
        "a push key with nobody to write to",
    ],
)
def test_each_way_of_being_unfit_is_named_by_its_variable(
    changes: dict[str, object], variable: str
) -> None:
    problems = staging(**changes).deploy_problems()
    assert len(problems) == 1, problems
    assert problems[0].startswith(variable), problems


def test_the_api_will_not_be_built_from_an_unfit_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dealerai import main

    unfit = staging(web_origins="http://localhost:3000", supabase_url=None)
    monkeypatch.setattr(main, "get_settings", lambda: unfit)
    with pytest.raises(RuntimeError) as refusal:
        main.create_app()
    # Every problem at once: nobody should fix one, deploy, and meet the next.
    assert "WEB_ORIGINS" in str(refusal.value) and "SUPABASE_URL" in str(refusal.value)


async def test_nor_will_the_worker_start_from_one(monkeypatch: pytest.MonkeyPatch) -> None:
    from dealerai import worker

    monkeypatch.setattr(worker, "get_settings", lambda: staging(storage_dir=".storage"))
    with pytest.raises(RuntimeError, match="STORAGE_DIR"):
        await worker.main()
