"""Apply supabase/migrations/*.sql in order, once each.

Run with: npm run db:migrate

Deliberately not Alembic: these are hand-written SQL migrations with roles,
policies and extensions in them, and Alembic's value is autogenerating diffs
from an ORM model we do not have.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
from pathlib import Path

import asyncpg

from ..config import get_settings, repo_root

#: Applied only when ENV=local. Supabase supplies auth.* and the platform roles.
LOCAL_ONLY = {"0000_local_shim.sql"}

TRACKING_TABLE = """
create table if not exists schema_migrations (
    filename    text primary key,
    checksum    text not null,
    applied_at  timestamptz not null default now()
)
"""

# This table is created by the runner, not by a file in supabase/migrations, so
# it never passes through the grants in 0001. On Supabase, new tables in public
# inherit default privileges for anon and authenticated — which handed INSERT,
# UPDATE, DELETE and TRUNCATE on the migration ledger to anyone holding the
# public anon key. Truncating it makes this runner replay every migration and
# fail. Revoked on every run, so it cannot drift back.
LOCK_DOWN_TRACKING = """
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on public.schema_migrations from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on public.schema_migrations from authenticated';
  end if;
end $$;
"""


def migrations_dir() -> Path:
    return repo_root() / "supabase" / "migrations"


def load_env_file(path: Path) -> None:
    """Load an alternate dotenv before settings are read.

    Deploying to staging means pointing this one script at a different database
    without touching .env — because a .env edit that outlives the deploy is how
    someone later runs the destructive test suite against production.
    Values here override the process environment on purpose: an explicit
    --env-file is a deliberate act.
    """
    if not path.is_file():
        raise FileNotFoundError(f"no env file at {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ[key.strip()] = value.strip()


async def run() -> int:
    settings = get_settings()
    directory = migrations_dir()
    files = sorted(p for p in directory.glob("*.sql"))
    if not files:
        print(f"no migrations found in {directory}")
        return 1

    conn = await asyncpg.connect(settings.migration_dsn)
    try:
        await conn.execute(TRACKING_TABLE)
        await conn.execute(LOCK_DOWN_TRACKING)
        applied = {
            r["filename"]: r["checksum"]
            for r in await conn.fetch("select filename, checksum from schema_migrations")
        }

        for path in files:
            if path.name in LOCAL_ONLY and not settings.is_local:
                print(f"skip   {path.name}  (local only, env={settings.env})")
                continue

            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]

            if path.name in applied:
                if applied[path.name] != checksum:
                    print(
                        f"ERROR  {path.name} was modified after being applied "
                        f"({applied[path.name]} -> {checksum}). "
                        "Write a new migration instead of editing an applied one."
                    )
                    return 1
                print(f"ok     {path.name}")
                continue

            print(f"apply  {path.name} ...", end=" ", flush=True)
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "insert into schema_migrations (filename, checksum) values ($1, $2)",
                    path.name,
                    checksum,
                )
            print("done")

        if settings.is_local:
            # Mirrors the one documented ops step, so local dev can actually
            # connect as the NOBYPASSRLS application role.
            await conn.execute("alter role dealerai_app login password 'dealerai_app'")
            print("ok     dealerai_app login enabled (local only)")
    finally:
        await conn.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply supabase/migrations in order.")
    parser.add_argument(
        "--env-file",
        help="dotenv to load first, e.g. .env.staging. Relative to the repo root.",
    )
    args = parser.parse_args()
    if args.env_file:
        path = Path(args.env_file)
        load_env_file(path if path.is_absolute() else repo_root() / path)
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
