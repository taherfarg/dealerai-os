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

    #: Gemini. Optional so the app boots without it; the gateway raises
    #: MissingAPIKey at call time rather than blocking startup for someone
    #: doing schema work.
    google_api_key: str | None = None

    #: Project URL, e.g. https://<ref>.supabase.co. Needed for Storage in T2.2.
    supabase_url: str | None = None

    #: Publishable/anon key. Safe to expose — RLS is what protects the data.
    #: The service_role key is deliberately NOT a setting: it bypasses RLS and
    #: must never be reachable from a request path. See docs/03 § 2.
    supabase_anon_key: str | None = None

    #: HS256 secret Supabase Auth signs user tokens with. Also signs invitation
    #: links, so they are invalidated by the same rotation.
    supabase_jwt_secret: str | None = None

    #: Fernet keys for channels.credentials, comma-separated, newest first.
    #: Rotation: prepend a new key, redeploy, re-save channels, drop the old one.
    credentials_keys: str | None = None

    #: Browser origins allowed to call the API, comma-separated. The web app talks
    #: to the API directly since docs/sales/01-architecture.md § 2 A.
    web_origins: str = "http://localhost:3000"

    #: Meta app secret. Every webhook body is verified against it
    #: (X-Hub-Signature-256); unset, every webhook is refused.
    whatsapp_app_secret: str | None = None

    #: The string Meta echoes back when the webhook subscription is verified.
    whatsapp_verify_token: str | None = None

    #: Graph API version the WhatsApp connector calls. Meta keeps a version about two years.
    whatsapp_graph_version: str = "v25.0"

    #: Web Push (docs/sales/07-frontend.md § 8). The private key is a base64url
    #: P-256 scalar — `npm run vapid:keys` writes one locally. Unset, nothing is
    #: pushed and the bell works as before. The subject is who a push service
    #: writes to about this sender: a real mailto: or https: address in
    #: production, where Apple refuses a made-up one.
    vapid_private_key: str | None = None
    vapid_subject: str = "mailto:push@dealerai.local"

    #: Local development only: stored objects live in this directory instead of
    #: Supabase Storage. Relative paths resolve against the repo root.
    storage_dir: str | None = None

    @property
    def migration_dsn(self) -> str:
        return self.migration_database_url or self.database_url

    @property
    def web_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.web_origins.split(",") if origin.strip()]

    @property
    def is_local(self) -> bool:
        return self.env == "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
