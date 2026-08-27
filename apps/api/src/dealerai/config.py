"""Every environment variable in the system is declared here and nowhere else.

A missing required setting fails at startup, by name, instead of at 2am with a
KeyError. `.env.example` is kept in sync by tests/test_config.py.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def repo_root() -> Path:
    """Walk up until package.json is found.

    Resolved rather than assumed, because the API is run from the repo root
    (`npm run api`) and the tests are run from apps/api — a CWD-relative .env
    would silently load in one case and silently not in the other.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "package.json").is_file():
            return parent
    raise FileNotFoundError(f"could not locate repo root from {__file__}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=repo_root() / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["local", "staging", "production"] = "local"
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    #: Connection used by the API and the worker. Must be a NOBYPASSRLS role
    #: (dealerai_app) — see supabase/migrations/0001_init.sql.
    database_url: str = Field(
        description="postgres://dealerai_app:...@host:5432/dealerai",
    )

    #: Elevated connection used only by the migration runner and test fixtures.
    #: Falls back to database_url when unset.
    migration_database_url: str | None = None

    db_pool_min: int = 1
    db_pool_max: int = 10

    @property
    def migration_dsn(self) -> str:
        return self.migration_database_url or self.database_url

    @property
    def is_local(self) -> bool:
        return self.env == "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
