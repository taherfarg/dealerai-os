from __future__ import annotations

from typing import Any

import asyncpg
import pytest
from google.genai import types
from pydantic import BaseModel

from conftest import TENANT_A
from dealerai.ai import gateway
from dealerai.ai.gateway import (
    ModelOutputInvalid,
    ModelRefusal,
    SystemLayers,
    complete,
)
from dealerai.ai.models import FLASH, FLASH_LITE, PRO, ROUTING, TaskKind, cost_usd
from dealerai.core.errors import BudgetExceeded
from dealerai.db.session import tenant_session

# --------------------------------------------------------------------------
# fake client
# --------------------------------------------------------------------------


def make_response(
    *,
    text: str = "ok",
    finish: types.FinishReason = types.FinishReason.STOP,
    prompt_tokens: int = 100,
    output_tokens: int = 50,
    cached_tokens: int = 0,
    thought_tokens: int = 0,
) -> types.GenerateContentResponse:
    parts = [types.Part(text=text)] if text else []
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=parts),
                finish_reason=finish,
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt_tokens,
            candidates_token_count=output_tokens,
            cached_content_token_count=cached_tokens,
            thoughts_token_count=thought_tokens,
            total_token_count=prompt_tokens + output_tokens,
        ),
    )


class FakeModels:
    def __init__(self, response: types.GenerateContentResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
        self.calls.append(kwargs)
        return self.response


class FakeAio:
    def __init__(self, response: types.GenerateContentResponse) -> None:
        self.models = FakeModels(response)


class FakeClient:
    def __init__(self, response: types.GenerateContentResponse) -> None:
        self.aio = FakeAio(response)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.aio.models.calls


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient(make_response())
    monkeypatch.setattr(gateway, "_client", client)
    return client


ROLE = SystemLayers(role="You are a test agent.", tenant="Brand: Alpha Motors.", context="ctx")
USER = [types.Content(role="user", parts=[types.Part(text="hi")])]


# --------------------------------------------------------------------------
# routing and cost — pure, no client
# --------------------------------------------------------------------------


def test_every_task_kind_is_routed() -> None:
    assert not [t for t in TaskKind if t not in ROUTING]


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        (TaskKind.ORCHESTRATE, PRO),
        (TaskKind.ADS_DECISION, PRO),
        (TaskKind.SALES_REPLY, FLASH),
        (TaskKind.COPYWRITE, FLASH),
        (TaskKind.CLASSIFY_INTENT, FLASH_LITE),
        (TaskKind.SPAM_FILTER, FLASH_LITE),
    ],
)
def test_routing_matches_the_documented_table(task: TaskKind, expected: Any) -> None:
    assert ROUTING[task] is expected


def test_no_preview_models_are_routed() -> None:
    """gemini-3-pro-preview was shut down while still the newest Pro. A model
    that disappears mid-quarter is an outage on the path where agents spend a
    dealer's ad budget."""
    previews = [s.model for s in ROUTING.values() if "preview" in s.model or "exp" in s.model]
    assert not previews, f"preview models on a production path: {previews}"


def test_cost_of_an_uncached_call() -> None:
    # 1M in + 1M out on Flash = $0.30 + $2.50
    assert cost_usd(FLASH, input_tokens=1_000_000, output_tokens=1_000_000) == pytest.approx(2.80)


def test_cached_tokens_are_a_discount_not_an_addition() -> None:
    """prompt_token_count INCLUDES cached_content_token_count.

    Treating them as separate buckets — which Anthropic's shape requires —
    would bill the cached portion twice and overstate every invoice.
    """
    total = cost_usd(FLASH, input_tokens=100_000, output_tokens=0, cached_tokens=90_000)
    expected = 10_000 * 0.30e-6 + 90_000 * 0.03e-6
    assert total == pytest.approx(expected)

    # Fully cached prompt: only the cached rate applies, nothing at full price.
    assert cost_usd(FLASH, input_tokens=1_000, output_tokens=0, cached_tokens=1_000) == (
        pytest.approx(1_000 * 0.03e-6)
    )


def test_cached_tokens_can_never_make_input_negative() -> None:
    assert cost_usd(FLASH, input_tokens=10, output_tokens=0, cached_tokens=999) >= 0


def test_thinking_tokens_are_billed_at_the_output_rate() -> None:
    """They are reported separately from candidates_token_count, so a
    reasoning-heavy call looks far cheaper than it is if they are dropped."""
    without = cost_usd(PRO, input_tokens=0, output_tokens=1_000)
    with_thoughts = cost_usd(PRO, input_tokens=0, output_tokens=1_000, thought_tokens=9_000)
    assert with_thoughts == pytest.approx(without * 10)


# --------------------------------------------------------------------------
# prompt layout
# --------------------------------------------------------------------------


def test_system_layers_render_stable_first() -> None:
    """Gemini caches on a repeated prefix, so ordering decides whether anything
    is cached at all — a varying value in `role` destroys the whole prefix."""
    assert ROLE.render() == "You are a test agent.\n\nBrand: Alpha Motors.\n\nctx"


def test_empty_layers_are_omitted_not_rendered_blank() -> None:
    assert SystemLayers(role="R").render() == "R"
    assert SystemLayers(role="R", context="C").render() == "R\n\nC"


async def test_system_instruction_is_sent(db: None, seeded: None, fake_client: FakeClient) -> None:
    await complete(TaskKind.SALES_REPLY, tenant_id=TENANT_A, system=ROLE, messages=USER)
    assert fake_client.calls[0]["config"].system_instruction == ROLE.render()


async def test_model_comes_from_the_routing_table(
    db: None, seeded: None, fake_client: FakeClient
) -> None:
    await complete(TaskKind.ORCHESTRATE, tenant_id=TENANT_A, system=ROLE, messages=USER)
    assert fake_client.calls[0]["model"] == "gemini-2.5-pro"


async def test_thinking_budget_is_off_for_classification(
    db: None, seeded: None, fake_client: FakeClient
) -> None:
    """Thinking on a spam check is pure latency and cost on the critical path
    of a customer reply."""
    await complete(TaskKind.CLASSIFY_INTENT, tenant_id=TENANT_A, system=ROLE, messages=USER)
    assert fake_client.calls[0]["config"].thinking_config.thinking_budget == 0


async def test_thinking_is_dynamic_for_reasoning(
    db: None, seeded: None, fake_client: FakeClient
) -> None:
    await complete(TaskKind.ORCHESTRATE, tenant_id=TENANT_A, system=ROLE, messages=USER)
    assert fake_client.calls[0]["config"].thinking_config.thinking_budget == -1


async def test_tools_are_sorted_so_the_prefix_is_stable(
    db: None, seeded: None, fake_client: FakeClient
) -> None:
    tools = [
        types.Tool(function_declarations=[types.FunctionDeclaration(name="zebra")]),
        types.Tool(function_declarations=[types.FunctionDeclaration(name="alpha")]),
    ]
    await complete(
        TaskKind.SALES_REPLY, tenant_id=TENANT_A, system=ROLE, messages=USER, tools=tools
    )
    sent = fake_client.calls[0]["config"].tools
    assert [t.function_declarations[0].name for t in sent] == ["alpha", "zebra"]


# --------------------------------------------------------------------------
# budget
# --------------------------------------------------------------------------


async def test_budget_is_checked_before_any_api_call(
    db: None, seeded: None, fake_client: FakeClient, su: asyncpg.Connection
) -> None:
    await su.execute(
        """insert into agent_traces (tenant_id, kind, name, cost_usd)
           values ($1, 'model', 'prior', 999)""",
        TENANT_A,
    )
    with pytest.raises(BudgetExceeded):
        await complete(TaskKind.SALES_REPLY, tenant_id=TENANT_A, system=ROLE, messages=USER)
    assert fake_client.calls == [], "money was spent after the budget was exhausted"


# --------------------------------------------------------------------------
# tracing
# --------------------------------------------------------------------------


async def test_trace_records_tokens_cost_and_cache_hits(
    db: None, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient(
        make_response(prompt_tokens=21_000, output_tokens=500, cached_tokens=20_000)
    )
    monkeypatch.setattr(gateway, "_client", client)

    result = await complete(
        TaskKind.SALES_REPLY,
        tenant_id=TENANT_A,
        system=ROLE,
        messages=USER,
        trace_name="unit-test",
    )

    # agent_traces is RLS-protected; a system session would correctly see nothing.
    async with tenant_session(TENANT_A) as conn:
        row = await conn.fetchrow(
            "select * from agent_traces where tenant_id=$1 and name='unit-test'", TENANT_A
        )
    assert row is not None
    assert row["model"] == "gemini-2.5-flash"
    assert row["input_tokens"] == 21_000
    assert row["cache_read_tokens"] == 20_000
    assert row["cache_write_tokens"] == 0, "Gemini has no cache-write step"
    assert float(row["cost_usd"]) == pytest.approx(result.cost_usd, rel=1e-4)


# --------------------------------------------------------------------------
# failure paths
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        types.FinishReason.SAFETY,
        types.FinishReason.PROHIBITED_CONTENT,
        types.FinishReason.RECITATION,
    ],
)
async def test_a_blocked_response_raises_rather_than_exploding_on_text(
    db: None, seeded: None, monkeypatch: pytest.MonkeyPatch, reason: types.FinishReason
) -> None:
    """A blocked candidate has no text part at all. `response.text` would raise
    from a property access; the caller needs a typed error it can act on."""
    monkeypatch.setattr(gateway, "_client", FakeClient(make_response(text="", finish=reason)))
    with pytest.raises(ModelRefusal):
        await complete(TaskKind.SALES_REPLY, tenant_id=TENANT_A, system=ROLE, messages=USER)


async def test_max_tokens_is_not_treated_as_a_refusal(
    db: None, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A truncated answer is still an answer; the caller decides what to do."""
    monkeypatch.setattr(
        gateway,
        "_client",
        FakeClient(make_response(text="partial", finish=types.FinishReason.MAX_TOKENS)),
    )
    result = await complete(TaskKind.SALES_REPLY, tenant_id=TENANT_A, system=ROLE, messages=USER)
    assert result.text == "partial"


async def test_a_refused_call_is_still_traced(
    db: None, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal costs money, so it has to appear in the bill."""
    monkeypatch.setattr(
        gateway,
        "_client",
        FakeClient(make_response(text="", finish=types.FinishReason.SAFETY)),
    )
    with pytest.raises(ModelRefusal):
        await complete(
            TaskKind.SALES_REPLY,
            tenant_id=TENANT_A,
            system=ROLE,
            messages=USER,
            trace_name="refused",
        )
    async with tenant_session(TENANT_A) as conn:
        row = await conn.fetchrow(
            "select status from agent_traces where tenant_id=$1 and name='refused'", TENANT_A
        )
    assert row is not None
    assert row["status"] == "SAFETY"


class Intent(BaseModel):
    intent: str
    confidence: float


async def test_structured_output_sets_schema_and_validates(
    db: None, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient(make_response(text='{"intent":"price","confidence":0.9}'))
    monkeypatch.setattr(gateway, "_client", client)

    result = await complete(
        TaskKind.CLASSIFY_INTENT,
        tenant_id=TENANT_A,
        system=ROLE,
        messages=USER,
        output_schema=Intent,
    )
    assert isinstance(result.parsed, Intent)
    assert result.parsed.intent == "price"

    config = client.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is Intent


async def test_malformed_structured_output_raises_typed_error(
    db: None, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gateway, "_client", FakeClient(make_response(text="not json at all")))
    with pytest.raises(ModelOutputInvalid):
        await complete(
            TaskKind.CLASSIFY_INTENT,
            tenant_id=TENANT_A,
            system=ROLE,
            messages=USER,
            output_schema=Intent,
        )


async def test_thought_parts_are_excluded_from_the_answer(
    db: None, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Thought summaries must never reach a customer."""
    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(text="internal reasoning", thought=True),
                        types.Part(text="the answer"),
                    ],
                ),
                finish_reason=types.FinishReason.STOP,
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=10, candidates_token_count=5, total_token_count=15
        ),
    )
    monkeypatch.setattr(gateway, "_client", FakeClient(response))
    result = await complete(TaskKind.ORCHESTRATE, tenant_id=TENANT_A, system=ROLE, messages=USER)
    assert result.text == "the answer"
    assert "internal reasoning" not in result.text


async def test_automatic_function_calling_is_disabled(
    db: None, seeded: None, fake_client: FakeClient
) -> None:
    """AFC is ON by default and would have the SDK execute tool callables inside
    the generate_content call — bypassing the autonomy gate, every guard, and the
    trace. The tool loop belongs to orchestrator/executor.py, which owns them."""
    await complete(TaskKind.SALES_REPLY, tenant_id=TENANT_A, system=ROLE, messages=USER)
    afc = fake_client.calls[0]["config"].automatic_function_calling
    assert afc is not None and afc.disable is True
