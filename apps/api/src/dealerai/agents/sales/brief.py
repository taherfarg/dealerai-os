"""One line for a manager's morning.

The rest of the brief is rows the screen renders in the reader's own language
(sales/dashboard.attention). This writes the only part that is prose — a
headline in both UI languages — from a block of numbers that names no
customer, so it cannot write one into a row that outlives them.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog

from ...ai.gateway import ModelOutputInvalid, SystemLayers, complete
from ...ai.models import TaskKind
from ...ai.prompts import load
from ...sales.dashboard import Headline

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class Written:
    headline: Headline | None
    cost_usd: float


async def write(*, tenant_id: UUID, run_id: UUID, facts: str) -> Written:
    """No `_rules`: they are the rules for writing to a customer ("never reveal
    internal figures"), and this line is nothing but internal figures, for the
    manager they belong to."""
    try:
        result = await complete(
            TaskKind.ANALYSIS,
            tenant_id=tenant_id,
            system=SystemLayers(role=load("brief")),
            messages=f"{facts}\n\nWrite the headline.",
            output_schema=Headline,
            run_id=run_id,
            trace_name="brief",
        )
    except ModelOutputInvalid:
        # One unusable attempt, as with a draft: the brief goes out without a
        # headline rather than failing the morning.
        log.warning("brief_unparseable")
        return Written(headline=None, cost_usd=0.0)
    headline = result.parsed if isinstance(result.parsed, Headline) else None
    return Written(headline=headline, cost_usd=result.cost_usd)
