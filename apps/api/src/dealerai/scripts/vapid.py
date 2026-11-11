"""A VAPID key for this machine's .env (`npm run vapid:keys`).

Written to the file, never to the terminal: a secret printed is a secret in a
scrollback, a log and a chat. The public half is not secret and is served at
GET /v1/push/key. Changing the key orphans every subscription made with the
old one, so a key that is already there is left alone.
"""

from __future__ import annotations

import re

from cryptography.hazmat.primitives.asymmetric import ec

from ..config import repo_root
from ..notifications.push import b64

LINE = re.compile(r"^VAPID_PRIVATE_KEY=.*$", re.M)


def main() -> int:
    path = repo_root() / ".env"
    text = path.read_text("utf-8") if path.exists() else ""
    existing = LINE.search(text)
    if existing and existing.group().partition("=")[2].strip():
        print("VAPID_PRIVATE_KEY is already set in .env; left alone.")
        return 0
    scalar = ec.generate_private_key(ec.SECP256R1()).private_numbers().private_value
    line = f"VAPID_PRIVATE_KEY={b64(scalar.to_bytes(32, 'big'))}"
    text = LINE.sub(line, text) if existing else f"{text.rstrip()}\n\n{line}\n"
    path.write_text(text, "utf-8")
    print("VAPID_PRIVATE_KEY written to .env. Restart the API and the worker.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
