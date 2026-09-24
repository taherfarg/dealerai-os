"""The draft agent. `converse` is stubbed: what is tested is what we ask for.

A model's answer is not ours to assert on — that is Task 12's eval. What is
ours is the prompt layering, the tool list, the retry, and the refusal to hand
the composer an empty box.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from dealerai.agents.sales import copilot
from dealerai.agents.sales.intent import Read
from dealerai.ai.gateway import ModelOutputInvalid
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
    assert asked[0]["tools"] == copilot.TOOLS


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
    assert "Leave `reply` empty" in asked[0]["prompt"]
    assert "bare value" in asked[0]["prompt"]


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
        rejected="Our final price is AED 235,000.",
    )
    assert "final price" in asked[0]["prompt"]
    assert "change nothing else" in asked[0]["prompt"]
    # A rewrite, not research: one model call instead of two.
    assert asked[0]["tools"] == []
    # The draft it is fixing, as data: told to fix one it could not see, the
    # retry came back empty.
    assert "<untrusted>\nOur final price is AED 235,000.\n</untrusted>" in asked[0]["prompt"]


async def test_a_workspace_without_opening_hours_says_so(asked: list[dict[str, Any]]) -> None:
    """Left unsaid, the model invented them — twice, differently each time."""
    await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(), read=_read())
    assert "Opening hours are not set" in asked[0]["system"].tenant


async def test_a_reserved_car_they_asked_about_is_named_on_the_turn(
    asked: list[dict[str, Any]],
) -> None:
    """Only when every car matching what they asked for is reserved: with an
    available one beside it, "the Patrol is reserved" would be untrue."""
    patrol = {
        "id": "p",
        "make": "Nissan",
        "model": "Patrol",
        "trim": "LE",
        "model_year": 2022,
        "price_minor": 21000000,
        "currency": "AED",
        "status": "reserved",
    }
    read = _read(entities={"model": "Patrol"})
    await copilot.write(
        tenant_id=TENANT, run_id=RUN, ground=replace(_ground(), vehicles=[patrol]), read=read
    )
    assert "Nissan Patrol they asked about is reserved" in asked[0]["prompt"]

    available = {**patrol, "id": "q", "status": "available"}
    await copilot.write(
        tenant_id=TENANT,
        run_id=RUN,
        ground=replace(_ground(), vehicles=[available, patrol]),
        read=read,
    )
    assert "is reserved" not in asked[1]["prompt"]


async def test_what_a_lookup_cannot_help_is_one_call(asked: list[dict[str, Any]]) -> None:
    """A greeting or a haggle is answered from the thread and the car it is
    about; a tool phase there only writes prose for the answer to rewrite."""
    await copilot.write(
        tenant_id=TENANT, run_id=RUN, ground=_ground(), read=_read(intent="negotiation")
    )
    assert asked[0]["tools"] == []


async def test_a_passage_carries_the_id_a_draft_cites_it_by(asked: list[dict[str, Any]]) -> None:
    """Cars are shown with their ids; a passage without one cannot be cited,
    and the draft shows no document chip however much of it the reply used."""
    passage = {
        "chunk_id": 330,
        "document_id": "d",
        "title": "Export policy",
        "heading": "Export › Customs",
        "content": "Customs are paid on arrival.",
    }
    await copilot.write(
        tenant_id=TENANT, run_id=RUN, ground=_ground(chunks=[passage]), read=_read()
    )
    assert "(chunk `330`)" in asked[0]["system"].context


async def test_passages_already_above_are_not_searched_for_again(
    asked: list[dict[str, Any]],
) -> None:
    """The handler retrieves with the customer's own words before drafting. A
    second search re-reads the prompt at the price of a model turn."""
    passage = {"chunk_id": 1, "document_id": "d", "title": "Export", "heading": "", "content": "x"}
    await copilot.write(
        tenant_id=TENANT, run_id=RUN, ground=_ground(chunks=[passage]), read=_read()
    )
    assert "search_knowledge" not in asked[0]["tools"]
    assert "search_inventory" in asked[0]["tools"]


async def test_arabic_in_latin_letters_is_asked_for_in_latin_letters(
    asked: list[dict[str, Any]],
) -> None:
    latin = _read(language="ar", script="latin")
    await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(), read=latin)
    assert "Latin letters" in asked[0]["prompt"]
    arabic = _read(language="ar", script="arabic")
    await copilot.write(tenant_id=TENANT, run_id=RUN, ground=_ground(), read=arabic)
    assert "Latin letters" not in asked[1]["prompt"]


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
        return Conversation(
            text="{}", parsed=copilot.Draft(reply="", language="en"), cost_usd=0.004
        )

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


async def test_a_reply_cut_off_at_the_ceiling_is_no_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    """The copilot eval's second run: one reply repeated itself until the
    output ceiling, the JSON arrived cut off, and the exception failed the
    whole event instead of blocking one draft."""

    async def fake(task: Any, **kwargs: Any) -> Conversation:
        raise ModelOutputInvalid("Draft validation failed: <root> json_invalid")

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


def test_the_reply_is_a_field_the_model_cannot_leave_out() -> None:
    """Schema decoding enforces `required` and nothing else. While `reply` was
    optional, one draft in seven came back as every field but the reply."""
    schema = copilot.Draft.model_json_schema()
    assert "reply" in schema["required"]
    assert schema["properties"]["reply"]["type"] == "string"
