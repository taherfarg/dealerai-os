"""Give the application its way into a hosted database.

    npm run db:app-password:staging -- --clipboard
    npm run --silent db:app-password:staging | <a host's command that reads secrets from a pipe>

The one step of a deployment that is not a migration, because it makes a
secret (docs/sales/10-staging.md § 2). It makes a password nobody chooses and
nobody sees, sets it on `dealerai_app`, proves that it signs in, and hands over
the application's whole address — onto the clipboard, or down a pipe. Never
onto a screen: a secret printed is a secret in a scrollback, a log and a chat.

The password does not travel in the statement either. `alter role … password
'x'` leaves `x` in the server's log. This sends what the server would have
stored anyway — the SCRAM verifier, as `psql`'s \\password does — so the log
holds nothing that signs in.

Run again, it makes another, and the one before stops working.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import secrets
import string
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from ..config import get_settings, repo_root
from .migrate import load_env_file

ROLE = "dealerai_app"
ITERATIONS = 4096


def new_password() -> str:
    """Letters and digits only, so an address can hold it as it is."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(40))


def scram_verifier(password: str, *, salt: bytes | None = None) -> str:
    """What Postgres stores for a password (RFC 5802), in the form it stores it."""

    def b64(raw: bytes) -> str:
        return base64.b64encode(raw).decode()

    salt = salt or secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    stored = hashlib.sha256(hmac.digest(salted, b"Client Key", "sha256")).digest()
    server = hmac.digest(salted, b"Server Key", "sha256")
    return f"SCRAM-SHA-256${ITERATIONS}:{b64(salt)}${b64(stored)}:{b64(server)}"


def address_for(role: str, password: str, migration_dsn: str) -> str:
    """The migration runner's address, as somebody else."""
    parts = urlsplit(migration_dsn)
    # Through Supabase's pooler a user carries its project: postgres.<project-ref>.
    _, dot, project = (parts.username or "").partition(".")
    where = (parts.hostname or "") + (f":{parts.port}" if parts.port else "")
    return urlunsplit(parts._replace(netloc=f"{role}{dot}{project}:{password}@{where}"))


async def _signs_in(address: str, role: str) -> None:
    """A pooler can take a moment to learn a new password."""
    for attempt in range(5):
        try:
            conn = await asyncpg.connect(address)
        except (asyncpg.InvalidPasswordError, asyncpg.InvalidAuthorizationSpecificationError):
            if attempt == 4:
                raise
            await asyncio.sleep(2)
            continue
        try:
            who, bypasses = await conn.fetchrow(
                """select current_user::text,
                          (select rolbypassrls from pg_roles where rolname = current_user)"""
            )
        finally:
            await conn.close()
        if who != role or bypasses:
            raise SystemExit(f"signed in as {who}, bypassing row-level security: {bypasses}")
        return


async def give_password(migration_dsn: str, *, role: str = ROLE) -> str:
    """Set a new password on the role and return the address it signs in with."""
    password = new_password()
    conn = await asyncpg.connect(migration_dsn)
    try:
        if not await conn.fetchval("select 1 from pg_roles where rolname = $1", role):
            raise SystemExit(f"there is no role {role}: has the schema been applied?")
        # A name and a verifier cannot be parameters. Neither came from outside:
        # the name is ours, and the verifier is base64 and punctuation.
        await conn.execute(f"alter role \"{role}\" login password '{scram_verifier(password)}'")
    finally:
        await conn.close()
    address = address_for(role, password, migration_dsn)
    # Proved before it is handed over: a secret that does not work is worse than none.
    await _signs_in(address, role)
    return address


def to_clipboard(text: str) -> None:
    tool = {"win32": ["clip"], "darwin": ["pbcopy"]}.get(sys.platform)
    if tool is None:
        raise SystemExit("this system has no clipboard to give it to: pipe it instead")
    subprocess.run(tool, input=text.encode(), check=True)


def on_a_screen() -> bool:
    return sys.stdout.isatty()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Give dealerai_app a password nobody sees.")
    parser.add_argument("--env-file", help="dotenv to load first, e.g. .env.staging")
    parser.add_argument(
        "--clipboard", action="store_true", help="put the address on the clipboard, not on a pipe"
    )
    args = parser.parse_args(argv)
    if args.env_file:
        path = Path(args.env_file)
        load_env_file(path if path.is_absolute() else repo_root() / path)
    settings = get_settings()
    if settings.is_local:
        print(
            "this is for a hosted database: on a laptop the migration runner sets the "
            "password everything expects",
            file=sys.stderr,
        )
        return 1
    # Decided before anything is changed: a new password that had nowhere to go
    # would have locked the application out for nothing.
    if not args.clipboard and on_a_screen():
        print(
            "nothing was changed. Say where the address is to go: --clipboard, or a pipe. "
            "It is never printed to a screen.",
            file=sys.stderr,
        )
        return 2

    address = asyncio.run(give_password(settings.migration_dsn, role=ROLE))
    if args.clipboard:
        to_clipboard(address)
        print(
            f"{ROLE} can sign in, and its address is on the clipboard. Paste it where "
            "DATABASE_URL is asked for, then copy something else.",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(f"DATABASE_URL={address}\n")
        print(f"{ROLE} can sign in; its address went down the pipe.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
