"""Prompts live as .md files so they show up in diffs and get reviewed."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache
def load(name: str) -> str:
    """Load a prompt by stem, e.g. load("_rules")."""
    path = _DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no prompt named {name!r} in {_DIR}")
    return path.read_text(encoding="utf-8").strip()
