from __future__ import annotations

from typing import Any

import asyncpg
import pytest
from anthropic.types import Message, TextBlock, ToolParam, Usage
from pydantic import BaseModel

from conftest import TENANT_A
from dealerai.ai import gateway
from dealerai.ai.gateway import (
    ModelOutputInvalid,
    ModelRefusal,
    SystemLayers,
    build_system,
    complete,
)
from dealerai.ai.models import HAIKU, OPUS, OPUS_XHIGH, ROUTING, SONNET, TaskKind, cost_usd
from dealerai.core.errors import BudgetExceeded
from dealerai.db.session import tenant_session

# --------------------------------------------------------------------------
# fake client
# --------------------------------------------------------------------------


def make_message(
    *,
    text: str = "ok",
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read: int = 0,
    cache_write: int = 0,
) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-sonnet-5",
        content=[TextBlock(type="text", text=text, citations=None)],
        stop_reason=stop_reason,  # type: ignore[arg-type]
        stop_sequence=None,
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


class FakeStream:
    def __init__(self, message: Message) -> None:
        self._message = message

    async def __aenter__(self) -> FakeStream:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_final_message(self) -> Message:
        return self._message


class FakeMessages:
    def __init__(self, message: Message) -> None:
        self.message = message
        self.calls: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> FakeStream:
        self.calls.append(kwargs)
        return FakeStream(self.message)


class FakeClient:
    def __init__(self, message: Message) -> None:
        self.messages = FakeMessages(message)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient(make_message())
    monkeypatch.setattr(gateway, "_client", client)
    return client


ROLE = SystemLayers(role="You are a test agent.", tenant="Brand: Alpha Motors.", context="ctx")


# --------------------------------------------------------------------------
# routing and cost — pure, no client
# --------------------------------------------------------------------------


def test_every_task_kind_is_routed() -> None:
    missing = [t for t in TaskKind if t not in ROUTING]
    assert not missing, f"unrouted task kinds: {missing}"


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        (TaskKind.ORCHESTRATE, OPUS_XHIGH),
        (TaskKind.ADS_DECISION, OPUS),
        (TaskKind.SALES_REPLY, SONNET),
        (TaskKind.COPYWRITE, SONNET),
        (TaskKind.CLASSIFY_INTENT, HAIKU),
        (TaskKind.SPAM_FILTER, HAIKU),
    ],
)
def test_routing_matches_the_documented_table(task: TaskKind, expected: Any) -> None:
    assert ROUTING[task] is expected


def test_cost_of_an_uncached_call() -> None:
    # 1M in + 1M out on Sonnet = $2 + $10
    assert cost_usd(SONNET, input_tokens=1_000_000, output_tokens=1_000_000) == pytest.approx(12.0)


def test_cache_reads_are_a_tenth_and_writes_a_quarter_more() -> None:
    """The whole cost model rests on these two multipliers."""
    read_only = cost_usd(SONNET, input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000)
    write_only = cost_usd(SONNET, input_tokens=0, output_tokens=0, cache_write_tokens=1_000_000)
    assert read_only == pytest.approx(0.20)
    assert write_only == pytest.approx(2.50)


def test_cached_input_is_additive_not_substitutive() -> None:
    """input_tokens from the API already excludes cached tokens."""
    total = cost_usd(SONNET, input_tokens=1_000, output_tokens=0, cache_read_tokens=99_000)
    assert total == pytest.approx(1_000 * 2e-6 + 99_000 * 2e-6 * 0.1)


# --------------------------------------------------------------------------
# prompt layout — the thing that silently costs 5x when wrong
# --------------------------------------------------------------------------


def test_cache_breakpoint_sits_on_the_last_stable_layer() -> None:
    blocks = build_system(ROLE)
    assert [b["text"] for b in blocks] == [ROLE.role, ROLE.tenant, ROLE.context]
    assert "cache_control" not in blocks[0]
    assert blocks[1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "cache_control" not in blocks[2], "a breakpoint below the varying layer caches nothing"


def test_breakpoint_falls_back_to_role_when_there_is_no_tenant_layer() -> None:
    blocks = build_system(SystemLayers(role="R", context="varies"))
    assert blocks[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert len(blocks) == 2


def test_there_is_exactly_one_breakpoint() -> None:
    blocks = build_system(ROLE)
    assert sum("cache_control" in b for b in blocks) == 1


async def test_tools_are_sorted_so_the_prefix_is_stable(
    db: None, seeded: None, fake_client: FakeClient
) -> None:
    """Tools render ahead of the system prompt; an unstable order kills every hit."""
    tools: list[ToolParam] = [
        {"name": "zebra", "description": "z", "input_schema": {"type": "object"}},
        {"name": "alpha", "description": "a", "input_schema": {"type": "object"}},
    ]
    await complete(
        TaskKind.SALES_REPLY,
        tenant_id=TENANT_A,
        system=ROLE,
        messages=[{"role": "user", "content": "hi"}],
        tools=tools,
    )
    sent = fake_client.messages.calls[0]["tools"]
    assert [t["name"] for t in sent] == ["alpha", "zebra"]


async def test_adaptive_thinking_never_sends_budget_tokens(
    db: None, seeded: None, fake_client: FakeClient
) -> None:
    """budget_tokens belongs to the older 'enabled' variant and 400s on these models."""
    await complete(
        TaskKind.SALES_REPLY,
        tenant_id=TENANT_A,
        system=ROLE,
        messages=[{"role": "user", "content": "hi"}],
    )
    thinking = fake_client.messages.calls[0]["thinking"]
    assert thinking == {"type": "adaptive"}
    assert "budget_tokens" not in thinking


async def test_effort_comes_from_the_routing_table(
    db: None, seeded: None, fake_client: FakeClient
) -> None:
    await complete(
        TaskKind.ORCHESTRATE,
        tenant_id=TENANT_A,
        system=ROLE,
        messages=[{"role": "user", "content": "plan"}],
    )
    call = fake_client.messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_config"]["effort"] == "xhigh"


# --------------------------------------------------------------------------
# budget
# --------------------------------------------------------------------------


async def test_budget_is_checked_before_any_api_call(
    db: None, seeded: None, fake_client: FakeClient, su: asyncpg.Connection
) -> None:
    """Refuse before spending, not after. The client must never be reached."""
    await su.execute(
        """insert into agent_traces (tenant_id, kind, name, cost_usd)
           values ($1, 'model', 'prior', 999)""",
        TENANT_A,
    )
    with pytest.raises(BudgetExceeded):
        await complete(
            TaskKind.SALES_REPLY,
            tenant_id=TENANT_A,
            system=ROLE,
            messages=[{"role": "user", "content": "hi"}],
        )
    assert fake_client.messages.calls == [], "money was spent after the budget was exhausted"


async def test_spend_under_budget_proceeds(
    db: None, seeded: None, fake_client: FakeClient, su: asyncpg.Connection
) -> None:
    await su.execute(
        """insert into agent_traces (tenant_id, kind, name, cost_usd)
           values ($1, 'model', 'prior', 1.5)""",
        TENANT_A,
    )
    result = await complete(
        TaskKind.SALES_REPLY,
        tenant_id=TENANT_A,
        system=ROLE,
        messages=[{"role": "user", "content": "hi"}],
    )
    assert result.text == "ok"


# --------------------------------------------------------------------------
# tracing
# --------------------------------------------------------------------------


async def test_trace_records_tokens_cost_and_cache_hits(
    db: None, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient(
        make_message(input_tokens=1_000, output_tokens=500, cache_read=20_000, cache_write=0)
    )
    monkeypatch.setattr(gateway, "_client", client)

    result = await complete(
        TaskKind.SALES_REPLY,
        tenant_id=TENANT_A,
        system=ROLE,
        messages=[{"role": "user", "content": "hi"}],
        trace_name="unit-test",
    )

    # Read through a tenant session: agent_traces is RLS-protected, and a
    # system session would correctly see nothing at all.
    async with tenant_session(TENANT_A) as conn:
        row = await conn.fetchrow(
            "select * from agent_traces where tenant_id = $1 and name = 'unit-test'", TENANT_A
        )
    assert row is not None
    assert row["model"] == "claude-sonnet-5"
    assert row["input_tokens"] == 1_000
    assert row["output_tokens"] == 500
    assert row["cache_read_tokens"] == 20_000
    assert float(row["cost_usd"]) == pytest.approx(result.cost_usd, rel=1e-4)
    assert row["latency_ms"] is not None


# --------------------------------------------------------------------------
# failure paths
# --------------------------------------------------------------------------


async def test_refusal_raises_before_content_is_read(
    db: None, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gateway, "_client", FakeClient(make_message(stop_reason="refusal", text=""))
    )
    with pytest.raises(ModelRefusal):
        await complete(
            TaskKind.SALES_REPLY,
            tenant_id=TENANT_A,
            system=ROLE,
            messages=[{"role": "user", "content": "hi"}],
        )


async def test_refused_call_is_still_traced(
    db: None, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal costs money, so it has to appear in the bill."""
    monkeypatch.setattr(
        gateway, "_client", FakeClient(make_message(stop_reason="refusal", text=""))
    )
    with pytest.raises(ModelRefusal):
        await complete(
            TaskKind.SALES_REPLY,
            tenant_id=TENANT_A,
            system=ROLE,
            messages=[{"role": "user", "content": "hi"}],
            trace_name="refused",
        )
    async with tenant_session(TENANT_A) as conn:
        row = await conn.fetchrow(
            "select status from agent_traces where tenant_id=$1 and name='refused'", TENANT_A
        )
    assert row is not None
    assert row["status"] == "refusal"


class Intent(BaseModel):
    intent: str
    confidence: float


async def test_structured_output_is_validated(
    db: None, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gateway,
        "_client",
        client := FakeClient(make_message(text='{"intent":"price","confidence":0.9}')),
    )
    result = await complete(
        TaskKind.CLASSIFY_INTENT,
        tenant_id=TENANT_A,
        system=ROLE,
        messages=[{"role": "user", "content": "how much"}],
        output_schema=Intent,
    )
    assert isinstance(result.parsed, Intent)
    assert result.parsed.intent == "price"
    fmt = client.messages.calls[0]["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert "properties" in fmt["schema"]


async def test_malformed_structured_output_raises_typed_error(
    db: None, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gateway, "_client", FakeClient(make_message(text="not json at all")))
    with pytest.raises(ModelOutputInvalid):
        await complete(
            TaskKind.CLASSIFY_INTENT,
            tenant_id=TENANT_A,
            system=ROLE,
            messages=[{"role": "user", "content": "x"}],
            output_schema=Intent,
        )
