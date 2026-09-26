"""Content agents. Importing this package registers every one of them.

Agents register at import time, so a module nobody imports is an agent the
planner cannot name and the executor cannot dispatch — and `validate_dag` then
rejects a perfectly good plan for referring to it.
"""

from __future__ import annotations

from . import copywriter, creative_director, enrichment, image, strategist

__all__ = ["copywriter", "creative_director", "enrichment", "image", "strategist"]
