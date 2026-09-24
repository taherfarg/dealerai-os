"""The tool loop. The gateway is stubbed; what is tested is the conversation we build."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from google.genai import types
from pydantic import BaseModel

from dealerai.ai.gateway import Completion, SystemLayers
from dealerai.ai.models import FLASH, TaskKind
from dealerai.core.security import AuthedUser
from dealerai.deps import TenantContext
from dealerai.orchestrator import toolloop


class Answer(BaseModel):
    reply: str


async def test_an_answer_written_without_tools_reaches_the_answer_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The copilot eval's empty drafts: the tool phase wrote the reply, the loop
    dropped it, and the schema phase was asked for what the tools returned —
    when no tool had run."""
    seen: list[list[Any]] = []

    async def fake(task: Any, *, messages: list[Any], **kwargs: Any) -> Completion:
        seen.append(messages)
        return Completion(
            text="AED 235,000.",
            response=types.GenerateContentResponse(candidates=[]),
            spec=FLASH,
            cost_usd=0.0,
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            thought_tokens=0,
            latency_ms=0,
            parsed=Answer(reply="AED 235,000."),
        )

    monkeypatch.setattr(toolloop, "complete", fake)
    ctx = TenantContext(
        tenant_id=uuid.uuid4(),
        user=AuthedUser(id=uuid.uuid4(), email=None, claims={}),
        role="sales",
    )
    monkeypatch.setattr(toolloop.registry, "declarations", lambda names: ["search_inventory"])
    await toolloop.converse(
        TaskKind.SALES_REPLY,
        ctx=ctx,
        system=SystemLayers(role="You reply."),
        prompt="How much is the Land Cruiser?",
        tools=["search_inventory"],
        output_schema=Answer,
    )

    answer_phase = seen[-1]
    assert [content.role for content in answer_phase] == ["user", "model", "user"]
    assert answer_phase[1].parts[0].text == "AED 235,000."


async def test_without_tools_the_answer_is_one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tool phase with nothing to call writes the answer as prose for the
    answer phase to write again as JSON — a second model turn for nothing."""
    seen: list[dict[str, Any]] = []

    async def fake(task: Any, **kwargs: Any) -> Completion:
        seen.append(kwargs)
        return Completion(
            text="{}",
            response=types.GenerateContentResponse(candidates=[]),
            spec=FLASH,
            cost_usd=0.0,
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            thought_tokens=0,
            latency_ms=0,
            parsed=Answer(reply="AED 235,000."),
        )

    monkeypatch.setattr(toolloop, "complete", fake)
    ctx = TenantContext(
        tenant_id=uuid.uuid4(),
        user=AuthedUser(id=uuid.uuid4(), email=None, claims={}),
        role="sales",
    )
    answer = await toolloop.converse(
        TaskKind.SALES_REPLY,
        ctx=ctx,
        system=SystemLayers(role="You reply."),
        prompt="Fix the draft.",
        tools=[],
        output_schema=Answer,
    )
    assert len(seen) == 1
    assert seen[0]["output_schema"] is Answer
    assert answer.parsed == Answer(reply="AED 235,000.")
    assert answer.hit_turn_limit is False
