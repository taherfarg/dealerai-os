"""Architectural constraints that a code review would otherwise have to catch.

These are the two rules from docs/08-folder-structure.md that, if broken, remove
a safety guarantee without breaking any feature — so nothing else would notice.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "dealerai"

ACQUIRE = re.compile(r"\.acquire\(\)")
CONNECT = re.compile(r"asyncpg\.(connect|create_pool)\(")


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_only_session_module_opens_connections() -> None:
    """If any other module could open a connection, it could open one with no
    tenant context — and RLS would have nothing to filter on."""
    allowed = {SRC / "db" / "session.py", SRC / "scripts" / "migrate.py"}
    offenders = [
        str(p.relative_to(SRC))
        for p in _python_files(SRC)
        if p not in allowed and (ACQUIRE.search(t := p.read_text("utf-8")) or CONNECT.search(t))
    ]
    assert not offenders, (
        f"these modules open their own database connection: {offenders}. "
        "Use dealerai.db.session.tenant_session instead."
    )


def test_agents_do_not_import_connectors() -> None:
    """Agents call tools; tools call connectors. An agent reaching a connector
    directly bypasses the guard layer without failing anything visibly."""
    agents = SRC / "agents"
    if not agents.exists():
        return  # agents land in M3
    offenders = [
        str(p.relative_to(SRC))
        for p in _python_files(agents)
        if re.search(r"^\s*(from|import)\s+.*connectors", p.read_text("utf-8"), re.M)
    ]
    assert not offenders, f"agents importing connectors directly: {offenders}"


def test_guards_stay_model_free() -> None:
    """Guards must be trivially testable and never depend on a model call."""
    guards = SRC / "guards"
    if not guards.exists():
        return  # guards land in M3
    offenders = [
        str(p.relative_to(SRC))
        for p in _python_files(guards)
        if re.search(r"^\s*(from|import)\s+.*\b(ai|anthropic)\b", p.read_text("utf-8"), re.M)
    ]
    assert not offenders, f"guards depending on the model layer: {offenders}"
