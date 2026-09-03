"""Real-API eval: prove implicit context caching actually engages.

Excluded from the default run (`-m 'not eval'`) because it costs money and
needs a key. Run it with: npm run eval:gateway

Everything else about the gateway is covered by stubs in tests/test_gateway.py.
This one exists because a cache regression is invisible — nothing breaks, the
bill just goes up 10x on the prompt — so the only honest check is a real round
trip.

Gemini caches implicitly: there is no breakpoint to place, the model finds the
common prefix itself. That makes the *ordering* of SystemLayers the whole
mechanism, and makes this test the only thing that proves the ordering works.
"""

from __future__ import annotations

import pytest
from google.genai import types

from conftest import TENANT_A
from dealerai.ai.gateway import SystemLayers, complete
from dealerai.ai.models import TaskKind
from dealerai.config import get_settings

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

#: Implicit caching has a minimum prefix length (a few thousand tokens on 2.5
#: models). Real tenant prompts — brand brain plus playbook plus retrieved
#: context — clear it easily; a toy prompt does not, so pad past it.
_BRAND = (
    "Alpha Motors is a Dubai dealership specialising in Chinese SUVs and sedans. "
    "Tone: confident, concise, never pushy. Always quote prices in AED. "
    "Never use the words cheap or bargain. Prefer 'value'. "
) * 400


async def test_second_identical_call_reads_from_cache(db: None, seeded: None) -> None:
    system = SystemLayers(
        role="You are a terse assistant. Answer in at most five words.",
        tenant=_BRAND,
        context="",
    )
    messages = [types.Content(role="user", parts=[types.Part(text="Say OK.")])]

    first = await complete(
        TaskKind.SALES_REPLY,
        tenant_id=TENANT_A,
        system=system,
        messages=messages,
        trace_name="eval-cache-1",
    )
    second = await complete(
        TaskKind.SALES_REPLY,
        tenant_id=TENANT_A,
        system=system,
        messages=messages,
        trace_name="eval-cache-2",
    )

    assert second.cached_tokens > 0, (
        "the second identical call cached nothing. Either the prefix is below "
        "the implicit-caching minimum, or something above it varies between "
        "calls — check for a timestamp, a request id, or an unsorted dict in "
        "the role or tenant layer."
    )
    assert second.cost_usd < first.cost_usd


async def test_a_real_call_returns_usable_text(db: None, seeded: None) -> None:
    """The smallest possible proof that the request shape is actually valid.

    Every parameter in the gateway was verified against the SDK's type stubs,
    not against the live API. This is the test that closes that gap.
    """
    result = await complete(
        TaskKind.CLASSIFY_INTENT,
        tenant_id=TENANT_A,
        system=SystemLayers(role="Reply with exactly the word: pong"),
        messages=[types.Content(role="user", parts=[types.Part(text="ping")])],
        trace_name="eval-smoke",
    )
    assert result.text.strip()
    assert result.input_tokens > 0
    assert result.cost_usd > 0
