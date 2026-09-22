"""The draft agent. `converse` is stubbed: what is tested is what we ask for.

A model's answer is not ours to assert on — that is Task 12's eval. What is
ours is the prompt layering, the tool list, the retry, and the refusal to hand
the composer an empty box.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from dealerai.agents.sales import copilot
from dealerai.agents.sales.intent import Read
from dealerai.ai.models import TaskKind
from dealerai.orchestrator.toolloop import Conversation
from dealerai.sales.grounding import Ground
from dealerai.sales.settings import SalesSettings

TENANT = uuid.uuid4()
RUN = uuid.uuid4()
NOW = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)


def _read(**over: Any) -> Read:
    return Read.model_validate(
        {"intent": "price", "confidence": 0.9, "language": "en", "script": "latin", **over}
    )


def _ground(*, window_open: bool = True, name: str = "Omar", **over: Any) -> Ground:
    return Ground(
        context={
            "conversation_id": uuid.uuid4(),
            "wa_window_expires_at": NOW.replace(hour=20) if window_open else NOW.replace(hour=1),
            "timezone": "Asia/Dubai",
            "currency": "AED",
            "tenant_name": "Pollux Motors",
            "full_name": name,
            "country": "AE",
            "profile": {},
            **over.pop("context", {}),
        },
        settings=SalesSettings(),
        tail=[{"direction": "in", "type": "text", "text": f"hello from {name}"}],
        notes=[],
        leads=[],
        vehicles=[
            {
                "id": str(uuid.uuid4()),
                "make": "Toyota",
                "model": "Land Cruiser",
                "trim": None,
                "model_year": 2023,
                "price_minor": 23500000,
                "currency": "AED",
                "status": "available",
            }
        ],
        templates=[
            {"name": "price_update", "language": "en", "category": "utility", "body": "Hi {{1}}"}
        ],
        now=NOW,
        **over,
    )


def _draft(**over: Any) -> copilot.Draft:
    return copilot.Draft.model_validate({"reply": "AED 235,000.", "language": "en", **over})


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every call to the tool loop, with what was asked for."""
    seen: list[dict[str, Any]] = []

    async def fake(task: Any, **kwargs: Any) -> Conversation:
        seen.append({"task": task, **kwargs})
        return Conversation(text="{}", parsed=_draft(), cost_usd=0.004, tool_calls=["get_vehicle"])

    monkeypatch.setattr(copilot, "converse", fake)
    return seen


async def test_the_cached_layers_do_not_change_between_two_drafts(
    asked: list[dict[str, Any]],
) -> None:
    """The whole economics of this feature. A tenant layer that varies caches
    nothing at all, and the bill triples without anything failing."""
    await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(name="Omar"), read=_read())
    await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(name="Karim"), read=_read())

    first, second = asked[0]["system"], asked[1]["system"]
    assert first.role == second.role
    assert first.tenant == second.tenant
    assert first.context != second.context  # the per-conversation half, correctly


async def test_the_role_layer_carries_the_hard_rules(asked: list[dict[str, Any]]) -> None:
    """_rules.md is where "never state a price you did not read from a tool"
    lives. A role layer without it is a different agent."""
    await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(), read=_read())
    role = asked[0]["system"].role
    assert "Never state a price you did not read from a tool" in role
    assert "You write the reply a salesperson" in role


async def test_nothing_that_changes_per_call_reaches_the_cached_layers(
    asked: list[dict[str, Any]],
) -> None:
    """A timestamp above the context is what silently destroys the prefix."""
    await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(), read=_read())
    above_the_context = asked[0]["system"].role + asked[0]["system"].tenant
    assert "Omar" not in above_the_context
    assert str(NOW.year) not in above_the_context


async def test_it_is_the_workhorse_tier(asked: list[dict[str, Any]]) -> None:
    await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(), read=_read())
    assert asked[0]["task"] is TaskKind.SALES_REPLY


async def test_four_tool_calls_is_the_ceiling(asked: list[dict[str, Any]]) -> None:
    """A model on its fifth lookup is lost rather than thorough."""
    await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(), read=_read())
    assert asked[0]["max_turns"] == 4


async def test_it_may_not_call_a_tool_that_writes() -> None:
    """Least privilege is a Python list, not a sentence in a prompt."""
    from dealerai import tools as _tools  # noqa: F401  registers them
    from dealerai.tools import registry

    for name in copilot.TOOLS:
        entry = registry.get(name)
        assert entry is not None, f"{name} is not a registered tool"
        assert entry.mutates is False


async def test_the_customer_360_is_in_the_prompt_rather_than_a_tool(
    asked: list[dict[str, Any]],
) -> None:
    """Three tools, not four. A tool re-reading what the prompt already holds
    is a turn of latency that can only disagree with it."""
    await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(), read=_read())
    assert "get_customer_360" not in copilot.TOOLS
    assert "Who you are writing to" in asked[0]["system"].context


async def test_a_closed_window_asks_for_a_template_by_name(asked: list[dict[str, Any]]) -> None:
    await copilot.write(
        tenant_id=TENANT, run_id=RUN, ground=_ground(window_open=False), read=_read()
    )
    assert "template_name" in asked[0]["prompt"]
    assert "Leave `reply` null" in asked[0]["prompt"]


async def test_an_open_window_says_nothing_about_templates(asked: list[dict[str, Any]]) -> None:
    await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(), read=_read())
    assert "template_name" not in asked[0]["prompt"]


async def test_the_intent_and_dialect_reach_the_instruction(asked: list[dict[str, Any]]) -> None:
    await copilot.write(
        tenant_id=TENANT,
        run_id=RUN,
        ground=_ground(),
        read=_read(intent="export_shipping", dialect="darija"),
    )
    assert "export_shipping" in asked[0]["prompt"]
    assert "darija" in asked[0]["prompt"]


async def test_a_retry_lists_the_findings_and_forbids_anything_else(
    asked: list[dict[str, Any]],
) -> None:
    """A model told only "that was wrong" rewrites the whole reply, and the
    second draft fails a different guard."""
    await copilot.write(
        tenant_id=TENANT,
        run_id=RUN,
        ground=_ground(),
        read=_read(),
        retry_because=["'final price' ends a negotiation nobody has had"],
    )
    assert "final price" in asked[0]["prompt"]
    assert "change nothing else" in asked[0]["prompt"]


async def test_the_customers_own_words_are_untrusted_in_the_context_layer(
    asked: list[dict[str, Any]],
) -> None:
    await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(), read=_read())
    assert "<untrusted>" in asked[0]["system"].context


async def test_the_draft_and_its_cost_come_back(asked: list[dict[str, Any]]) -> None:
    drafted = await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(), read=_read())
    assert drafted.draft is not None and drafted.draft.reply == "AED 235,000."
    assert drafted.cost_usd == 0.004
    assert drafted.tool_calls == ("get_vehicle",)


async def test_an_empty_draft_is_no_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Draft with neither reply nor template validates and says nothing. The
    composer would show an empty box, which reads as a broken product."""

    async def fake(task: Any, **kwargs: Any) -> Conversation:
        return Conversation(text="{}", parsed=copilot.Draft(language="en"), cost_usd=0.004)

    monkeypatch.setattr(copilot, "converse", fake)
    drafted = await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(), read=_read())
    assert drafted.draft is None
    assert drafted.cost_usd == 0.004  # it was still paid for


async def test_an_answer_that_is_not_a_draft_is_no_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(task: Any, **kwargs: Any) -> Conversation:
        return Conversation(text="", parsed=None, cost_usd=0.001)

    monkeypatch.setattr(copilot, "converse", fake)
    drafted = await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(), read=_read())
    assert drafted.draft is None


def test_the_prompt_keeps_its_arabic_and_french_examples() -> None:
    """They are the specification of tone, not decoration. Paraphrasing them
    into English is how a Gulf customer gets Modern Standard Arabic back."""
    from dealerai.ai.prompts import load

    prompt = load("sales_copilot")
    assert "تحب تشوفها السبت" in prompt  # Gulf
    assert "تحب تعدّي تشوفها" in prompt  # Egyptian
    assert "Vous le voulez pour l'export" in prompt  # French

    # Every Arabic example writes its price in Latin digits, because that is
    # what the rule two paragraphs above it demands. The rule itself quotes the
    # Arabic-Indic form as the thing not to do, so a blanket "no Arabic digits
    # anywhere" assertion would fail on the rule that forbids them.
    arabic_examples = [
        line for line in prompt.splitlines() if line.startswith("> ") and "AED" in line
    ]
    assert arabic_examples
    assert all("AED 235,000" in line or "AED 165,000" in line for line in arabic_examples)


def _free_form_objects(schema: Any, path: str = "") -> list[str]:
    """Every place a schema says "any object at all"."""
    found: list[str] = []
    if isinstance(schema, dict):
        if schema.get("additionalProperties") not in (None, False):
            found.append(path or "<root>")
        for key, value in schema.items():
            found += _free_form_objects(value, f"{path}.{key}" if path else key)
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            found += _free_form_objects(value, f"{path}[{index}]")
    return found


def test_no_schema_we_send_asks_for_a_free_form_object() -> None:
    """Gemini's Developer API refuses `additionalProperties` outright:

        additionalProperties is only supported in Gemini Enterprise Agent
        Platform mode, not in Gemini Developer API mode

    A `dict[str, Any]` field is exactly what renders it. Every unit test
    stubbed the model and passed; the first live draft failed on it, twelve
    seconds and half a cent in.
    """
    from dealerai.agents.sales.intent import Read as IntentRead

    for model in (copilot.Draft, copilot.ProposedAction, IntentRead):
        offenders = _free_form_objects(model.model_json_schema())
        assert not offenders, f"{model.__name__} has free-form objects at {offenders}"
