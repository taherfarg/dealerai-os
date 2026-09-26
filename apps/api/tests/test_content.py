"""The content factory, W3 end to end.

The model is stubbed by *what was asked of it*: the fake client reads the
response schema off the request and answers with that shape. That keeps the
whole DAG exercisable without spending money, and without a per-agent mock that
would drift from what the agents actually send.

Whether the strategist plans a *good* set is a model question and lives in
tests/evals/test_content_live.py.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from google.genai import types

from conftest import TENANT_A, USER_A, reseed
from dealerai import agents as _agents  # noqa: F401  registers the agents
from dealerai import tools as _tools  # noqa: F401  registers the tools
from dealerai.agents.content import image, strategist
from dealerai.agents.content.copywriter import _facts
from dealerai.ai import gateway
from dealerai.config import get_settings
from dealerai.media import compositor, storage
from dealerai.orchestrator import planner
from dealerai.orchestrator.executor import PlannedTask, execute_run

#: No module-scoped loop here, unlike tests/media: the `db` fixture builds the
#: connection pool on the test's own loop, and a pool created on one loop and
#: used from another fails as "another operation is in progress" — which reads
#: like a concurrency bug and is not one. The cost is a browser launch per test.

PLAN = {
    "reasoning": "Two pieces: the car itself, and one detail nobody has posted.",
    "briefs": [
        {
            "concept": "hero",
            "vehicle_id": "VEHICLE",
            "angle": "The one that arrived",
            "kind": "post",
        },
        {"concept": "feature", "vehicle_id": "VEHICLE", "angle": "The cabin", "kind": "post"},
    ],
}
CHOICE = {"template_key": "hero", "photo_index": 0, "rationale": "front three-quarter"}
COPY = {
    "hook": "It is here.",
    "caption": "The Patrol landed this morning. Come and look at it.",
    "cta": "DM to book a viewing",
    "hashtags": ["#Patrol", "#Dubai"],
    "alt_text": "A dark SUV in a showroom.",
    "headline": "Nissan Patrol",
    "subhead": "2023 · 18,000 km",
}


#: Set by the `clean` fixture. The stubbed plan names a real car, because a
#: brief pointing at nothing exercises the failure path rather than the flow.
VEHICLE: dict[str, str] = {"id": ""}


def _answer(schema: Any) -> str:
    """What a call asking for this schema should get back."""
    name = getattr(schema, "__name__", "")
    if name == "Plan":
        return json.dumps(PLAN).replace("VEHICLE", VEHICLE["id"])
    if name == "Choice":
        return json.dumps(CHOICE)
    if name == "Copy":
        return json.dumps(COPY)
    return "{}"


class _Models:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
        self.calls.append(kwargs)
        text = _answer(kwargs["config"].response_schema)
        return types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(role="model", parts=[types.Part(text=text)]),
                    finish_reason=types.FinishReason.STOP,
                )
            ],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=200, candidates_token_count=80, total_token_count=280
            ),
        )


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> _Models:
    models = _Models()
    monkeypatch.setattr(
        gateway, "_client", type("C", (), {"aio": type("A", (), {"models": models})()})()
    )
    return models


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Storage stubbed: the bucket is a deployment concern, and a test that
    needs one is a test nobody can run."""
    saved: list[str] = []

    async def _upload(path: str, data: bytes, *, content_type: str) -> str:
        saved.append(path)
        return path

    async def _download(path: str) -> bytes:
        return b"\xff\xd8\xff\xe0not-a-real-jpeg"

    monkeypatch.setattr(storage, "upload", _upload)
    monkeypatch.setattr(storage, "download", _download)
    return saved


@pytest.fixture
def clean(_migrated: None) -> Iterator[uuid.UUID]:
    asyncio.run(reseed())
    vehicle_id = asyncio.run(_seed_vehicle())
    VEHICLE["id"] = str(vehicle_id)
    yield vehicle_id


async def _seed_vehicle(photos: int = 8) -> uuid.UUID:
    vehicle_id = uuid.uuid4()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            """insert into vehicles (id, tenant_id, make, model, model_year, mileage_km,
                                     price_minor, currency, engine, power_hp, stock_number, status)
               values ($1,$2,'Nissan','Patrol',2023,18000,31000000,'AED','5.6L V8',400,'NS-1',
                       'available')""",
            vehicle_id,
            TENANT_A,
        )
        for i in range(photos):
            await conn.execute(
                """insert into vehicle_media
                     (tenant_id, vehicle_id, kind, storage_path, angle, quality_score,
                      is_hero, sort_order, qa)
                   values ($1,$2,'photo',$3,$4,0.9,$5,$6,'{"rejected": false}'::jsonb)""",
                TENANT_A,
                vehicle_id,
                f"{TENANT_A}/vehicles/{vehicle_id}/{i}.jpg",
                "front_three_quarter" if i == 0 else "interior_front",
                i == 0,
                i,
            )
    finally:
        await conn.close()
    return vehicle_id


async def _items(run_id: uuid.UUID) -> list[dict[str, Any]]:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        rows = await conn.fetch(
            """select c.id, c.status, c.concept, c.rejection_reason,
                      c.brief->>'template_key' as template,
                      array_agg(distinct p.locale) filter (where p.locale is not null) as locales,
                      array_agg(distinct a.aspect_ratio) filter (where a.id is not null) as ratios
                 from content_items c
                 left join content_copy p on p.content_item_id = c.id
                 left join content_assets a on a.content_item_id = c.id
                where c.run_id = $1 group by c.id""",
            run_id,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _run(vehicle_id: uuid.UUID, **overrides: Any) -> uuid.UUID:
    run_id = await planner.create_run(
        tenant_id=TENANT_A,
        goal="sell the Patrol",
        tasks=[
            PlannedTask(
                task_key="plan",
                agent="content_strategist",
                input={
                    "vehicle_ids": [str(vehicle_id)],
                    "objective": "sell the Patrol",
                    "count": 2,
                    "locales": ["en", "ar"],
                    **overrides,
                },
            )
        ],
        autonomy="autopilot",
    )
    await execute_run(TENANT_A, run_id)
    return run_id


# --------------------------------------------------------------------------
# fanning out — pure
# --------------------------------------------------------------------------


def test_each_brief_becomes_direct_write_render() -> None:
    briefs = [strategist.Brief(concept="hero", vehicle_id="v", angle="a")]
    spawned = strategist._fan_out(briefs, locales=["en", "ar"])
    assert [s.task_key for s in spawned] == [
        "b1_direct",
        "b1_copy_en",
        "b1_copy_ar",
        "b1_render",
    ]


def test_copy_waits_for_direction_because_the_template_decides_the_words() -> None:
    """A carousel card and a story teaser want different copy, and the template
    is what says which one this is."""
    spawned = strategist._fan_out(
        [strategist.Brief(concept="hero", vehicle_id="v", angle="a")], locales=["en"]
    )
    copy = next(s for s in spawned if s.task_key.endswith("copy_en"))
    assert copy.depends_on == ("b1_direct",)


def test_the_render_waits_for_every_language() -> None:
    """Otherwise a piece is composited while it is still half-written."""
    spawned = strategist._fan_out(
        [strategist.Brief(concept="hero", vehicle_id="v", angle="a")], locales=["en", "ar", "fr"]
    )
    render = next(s for s in spawned if s.task_key.endswith("render"))
    assert set(render.depends_on) == {"b1_direct", "b1_copy_en", "b1_copy_ar", "b1_copy_fr"}


def test_briefs_do_not_depend_on_each_other() -> None:
    """One bad brief must not take the batch with it — partial success is a
    normal outcome (docs/05 § 4)."""
    briefs = [strategist.Brief(concept="hero", vehicle_id="v", angle=str(i)) for i in range(3)]
    spawned = strategist._fan_out(briefs, locales=["en"])
    for spawn in spawned:
        prefix = spawn.task_key.split("_")[0]
        assert all(d.startswith(prefix) for d in spawn.depends_on)


# --------------------------------------------------------------------------
# what the copywriter is told
# --------------------------------------------------------------------------


def test_the_price_is_spelled_out_not_handed_over_in_minor_units() -> None:
    """Handing a model 31000000 and hoping is how a caption says AED 31,000,000
    for a Patrol."""
    facts = _facts({"price_minor": 31000000, "currency": "AED", "make": "Nissan"})
    assert "AED 31,000,000" not in facts
    assert "price: AED 310,000" in facts


def test_a_three_decimal_currency_is_not_off_by_ten() -> None:
    facts = _facts({"price_minor": 31000000, "currency": "KWD"})
    assert "price: KWD 31,000" in facts


def test_the_discount_floor_is_never_shown_to_the_copywriter() -> None:
    facts = _facts({"price_minor": 31000000, "min_price_minor": 28000000, "currency": "AED"})
    assert "28" not in facts


def test_verified_selling_points_are_offered() -> None:
    facts = _facts({"specs": {"usps": [{"text": "Barely driven", "basis": "mileage_km"}]}})
    assert "Barely driven" in facts


# --------------------------------------------------------------------------
# sorting upstream outputs
# --------------------------------------------------------------------------


def test_copy_is_keyed_by_the_language_it_says_it_is() -> None:
    """`from_tasks` arrives keyed by task, and a task key is not a locale — it
    is the only thing that survives a renamed task."""
    direction, copies = image._split(
        image.Input(
            from_tasks={
                "b1_direct": {"template_key": "hero", "content_item_id": "x"},
                "weird_key": {"locale": "ar", "caption": "مرحبا"},
            }
        )
    )
    assert direction["template_key"] == "hero"
    assert set(copies) == {"ar"}


def test_a_missing_upstream_output_is_not_a_crash() -> None:
    assert image._split(image.Input(from_tasks={"x": {}})) == ({}, {})


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------


async def test_a_content_run_produces_a_finished_piece_per_brief(
    db: None, clean: uuid.UUID, model: _Models, stored: list[str]
) -> None:
    run_id = await _run(clean)
    items = await _items(run_id)

    assert len(items) == 2, "one content item per brief"
    for item in items:
        assert item["status"] == "pending_approval", item["rejection_reason"]
        assert sorted(item["locales"]) == ["ar", "en"], "both languages written"
        assert sorted(item["ratios"]) == sorted(compositor.manifest(item["template"]).aspect_ratios)


async def test_every_ratio_the_template_declares_is_rendered(
    db: None, clean: uuid.UUID, model: _Models, stored: list[str]
) -> None:
    """Not four fixed ratios for everything: a story teaser at 16:9 is nonsense,
    so the template declares what it supports and every one of those is
    produced. The plan's "four aspect ratios" holds for hero and offer, which
    are the concepts that declare four."""
    run_id = await _run(clean)
    items = await _items(run_id)
    assert {i["template"] for i in items} == {"hero", "feature"}, (
        "the director is choosing per concept, not always the same template"
    )
    expected = 0
    for item in items:
        ratios = compositor.manifest(item["template"]).aspect_ratios
        assert set(item["ratios"]) == set(ratios)
        expected += len(ratios) * 2  # two languages
    assert len(stored) == expected


async def test_the_strategist_grows_the_run_rather_than_guessing_its_size(
    db: None, clean: uuid.UUID, model: _Models, stored: list[str]
) -> None:
    run_id = await _run(clean)
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        keys = [
            r["task_key"]
            for r in await conn.fetch(
                "select task_key from agent_tasks where run_id = $1 order by task_key", run_id
            )
        ]
    finally:
        await conn.close()
    assert keys[0] == "b1_copy_ar"
    assert "plan" in keys
    assert len(keys) == 1 + 2 * 4, "one plan task, then direct+2 copies+render per brief"


async def test_the_run_finishes_completed(
    db: None, clean: uuid.UUID, model: _Models, stored: list[str]
) -> None:
    run_id = await _run(clean)
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        status = await conn.fetchval("select status from agent_runs where id = $1", run_id)
    finally:
        await conn.close()
    assert status == "completed"


# --------------------------------------------------------------------------
# the guards, where they actually bite
# --------------------------------------------------------------------------


async def test_a_caption_quoting_the_wrong_price_never_becomes_an_asset(
    db: None, clean: uuid.UUID, model: _Models, stored: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The zero-tolerance case. The copy is fine in every other way and the
    figure is close enough to look right."""
    monkeypatch.setitem(COPY, "caption", "Yours from AED 295,000 this month.")
    try:
        run_id = await _run(clean)
    finally:
        COPY["caption"] = "The Patrol landed this morning. Come and look at it."

    items = await _items(run_id)
    assert items, "no content items at all"
    for item in items:
        assert item["status"] == "rejected"
        assert "295,000" in item["rejection_reason"]
        assert not item["ratios"], "a rejected piece must not leave assets behind"
    assert stored == [], "nothing was uploaded"


async def test_a_car_that_sold_mid_run_is_not_marketed(
    db: None, clean: uuid.UUID, model: _Models, stored: list[str]
) -> None:
    """Status is re-read at render time rather than trusted from the brief. A
    car can sell while a run is in flight, and this is the last moment before
    an asset exists."""
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute("update vehicles set status = 'sold' where id = $1", clean)
    finally:
        await conn.close()

    run_id = await _run(clean)
    items = await _items(run_id)
    assert items
    assert all(i["status"] == "rejected" for i in items)
    assert all("not available" in i["rejection_reason"] for i in items)


async def test_a_rejected_piece_keeps_its_reasons_and_its_copy(
    db: None, clean: uuid.UUID, model: _Models, stored: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nobody's work is thrown away. A human opens the queue and sees what was
    written and why it was stopped."""
    monkeypatch.setitem(COPY, "caption", "The cheapest Patrol in Dubai, AED 999,999.")
    try:
        run_id = await _run(clean)
    finally:
        COPY["caption"] = "The Patrol landed this morning. Come and look at it."

    items = await _items(run_id)
    assert all(sorted(i["locales"]) == ["ar", "en"] for i in items), "the copy survived"
    reasons = " ".join(i["rejection_reason"] for i in items)
    assert "999,999" in reasons
    assert "cheapest" in reasons


# --------------------------------------------------------------------------
# the endpoint
# --------------------------------------------------------------------------


def test_generate_returns_before_the_work_happens(_migrated: None) -> None:
    from fastapi.testclient import TestClient

    from dealerai.core.security import mint_test_token
    from dealerai.main import app

    secret = "super-secret-jwt-token-with-at-least-32-characters-long"
    get_settings().supabase_jwt_secret = secret
    asyncio.run(reseed())
    vehicle_id = asyncio.run(_seed_vehicle(photos=1))

    with TestClient(app) as client:
        headers = {
            "Authorization": f"Bearer {mint_test_token(USER_A, secret=secret)}",
            "X-Tenant-Id": str(TENANT_A),
        }
        response = client.post(
            "/v1/content/generate",
            json={"vehicle_ids": [str(vehicle_id)], "count": 3},
            headers=headers,
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]

        detail = client.get(f"/v1/runs/{run_id}", headers=headers).json()
        assert [t["task_key"] for t in detail["tasks"]] == ["plan"]
        assert detail["tasks"][0]["status"] == "pending", "the request did not run any agents"

        assert client.get(f"/v1/content?run_id={run_id}", headers=headers).json() == []
