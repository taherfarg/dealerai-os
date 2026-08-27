"""Apply supabase/migrations/*.sql in order, once each.

Run with: npm run db:migrate

Deliberately not Alembic: these are hand-written SQL migrations with roles,
policies and extensions in them, and Alembic's value is autogenerating diffs
from an ORM model we do not have.
"""

from __future__ import annotations

import asyncio
import hashlib
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


def migrations_dir() -> Path:
    return repo_root() / "supabase" / "migrations"


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
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
