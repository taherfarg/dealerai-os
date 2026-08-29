"""Real-API eval: prove prompt caching actually engages.

Excluded from the default run (`-m 'not eval'`) because it costs money and
needs a key. Run it with: npm run eval:gateway

Everything else about the gateway is covered by stubs in tests/test_gateway.py.
This one exists because a cache regression is invisible — nothing breaks, the
bill just quintuples — so the only honest check is a real round trip.
"""

from __future__ import annotations

import pytest

from conftest import TENANT_A
from dealerai.ai.gateway import SystemLayers, complete
from dealerai.ai.models import TaskKind
from dealerai.config import get_settings

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        not get_settings().anthropic_api_key,
        reason="ANTHROPIC_API_KEY not set",
    ),
]

# Caching needs a prefix above the model's minimum (~1k tokens), so pad the
# stable layers past it. Real tenant prompts clear this easily.
_BRAND = (
    "Alpha Motors is a Dubai dealership specialising in Chinese SUVs and sedans. "
    "Tone: confident, concise, never pushy. Always quote prices in AED. "
    "Never use the words cheap or bargain. Prefer 'value'. "
) * 40


async def test_second_identical_call_reads_from_cache(db: None, seeded: None) -> None:
    system = SystemLayers(
        role="You are a terse assistant. Answer in at most five words.",
        tenant=_BRAND,
        context="",
    )
    messages = [{"role": "user", "content": "Say OK."}]

    first = await complete(
        TaskKind.CLASSIFY_INTENT,
        tenant_id=TENANT_A,
        system=system,
        messages=messages,  # type: ignore[arg-type]
        trace_name="eval-cache-1",
    )
    second = await complete(
        TaskKind.CLASSIFY_INTENT,
        tenant_id=TENANT_A,
        system=system,
        messages=messages,  # type: ignore[arg-type]
        trace_name="eval-cache-2",
    )

    assert first.cache_write_tokens > 0, (
        "the first call wrote nothing to cache — the stable prefix is probably "
        "below the minimum cacheable length"
    )
    assert second.cache_read_tokens > 0, (
        "the second identical call did not read from cache. Something above the "
        "breakpoint varies between calls — check for a timestamp, a request id, "
        "or an unsorted dict in the role or tenant layer."
    )
    assert second.cost_usd < first.cost_usd
