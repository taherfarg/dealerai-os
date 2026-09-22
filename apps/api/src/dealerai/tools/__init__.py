"""Tools an agent may call. See docs/02-agent-architecture.md § 4.

Importing this package registers every tool, for the same reason the event
handlers package does: a module nobody imports contributes nothing to the
registry, and the failure is silent.
"""

from __future__ import annotations

from . import brand, content, inventory, knowledge

__all__ = ["brand", "content", "inventory", "knowledge"]
