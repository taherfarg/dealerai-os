"""Live eval: the W3 acceptance, with the real model.

Excluded from the default run. `npm run eval:content`

test_content.py proves the machinery — the DAG, the guards, the writes — with a
stubbed model. This is the only place that answers the question the plan
actually asks: given one car and eight photographs, does a real strategist plan
eight sensible pieces, and does everything downstream survive its own guards?

One Pro call plus roughly two dozen Flash calls per run, so the run happens once
and every assertion reads the same result.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg
import pytest

from conftest import TENANT_A
from dealerai import agents as _agents  # noqa: F401  registers the agents
from dealerai import tools as _tools  # noqa: F401  registers the tools
from dealerai.config import get_settings
from dealerai.media import compositor, storage
from dealerai.orchestrator import planner
from dealerai.orchestrator.executor import PlannedTask, execute_run

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

PIECES = 8

Produced = tuple[list[dict[str, Any]], uuid.UUID]


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Storage stubbed. The bucket is a deployment concern and this eval is
    about what the model produces, not about where the bytes land."""
    saved: list[str] = []

    async def _upload(path: str, data: bytes, *, content_type: str) -> str:
        saved.append(path)
        return path

    async def _download(path: str) -> bytes:
        return b""

    monkeypatch.setattr(storage, "upload", _upload)
    monkeypatch.setattr(storage, "download", _download)
    return saved


async def _seed(su: asyncpg.Connection) -> uuid.UUID:
    """One well-photographed car, priced, with a confirmed brand."""
    vehicle_id = uuid.uuid4()
    await su.execute(
        """insert into vehicles (id, tenant_id, make, model, trim, model_year, mileage_km,
                                 price_minor, currency, engine, power_hp, transmission,
                                 fuel, seats, exterior_color, interior_color, features,
                                 stock_number, status, listed_at)
           values ($1,$2,'Nissan','Patrol','Platinum',2023,18000,31000000,'AED','5.6L V8',
                   400,'7-speed automatic','petrol',8,'Pearl White','Black leather',
                   $3,'NS-4471','available', now() - interval '75 days')""",
        vehicle_id,
        TENANT_A,
        ["Sunroof", "360 camera", "Adaptive cruise", "Bose audio"],
    )
    angles = [
        "front_three_quarter",
        "front",
        "side",
        "rear_three_quarter",
        "interior_front",
        "dashboard",
        "detail",
        "wheel",
    ]
    for i, angle in enumerate(angles):
        await su.execute(
            """insert into vehicle_media (tenant_id, vehicle_id, kind, storage_path, angle,
                                          quality_score, is_hero, sort_order, qa)
               values ($1,$2,'photo',$3,$4,$5,$6,$7,'{"rejected": false}'::jsonb)""",
            TENANT_A,
            vehicle_id,
            f"{TENANT_A}/vehicles/{vehicle_id}/{i}.jpg",
            angle,
            0.92 - i * 0.03,
            i == 0,
            i,
        )
    await su.execute(
        """insert into brand_profiles (tenant_id, display_name, tone, cta_styles,
                                       required_disclaimers, colors)
           values ($1,'Alpha Motors',$2,$3,$4,$5)
           on conflict (tenant_id) do nothing""",
        TENANT_A,
        # `su` is a bare connection, without the pool's jsonb codec.
        json.dumps({"voice": "confident", "person": "we", "emoji": "sparse"}),
        # Per language, which is how a real dealership configures them — and
        # what a language-blind check would have blocked every Arabic piece over.
        json.dumps(
            [
                {"text": "DM to book a viewing", "locale": "en"},
                {"text": "Visit our showroom", "locale": "en"},
                {"text": "راسلنا لحجز معاينة", "locale": "ar"},
            ]
        ),
        json.dumps({}),
        json.dumps({"primary": "#0A2540", "secondary": "#C8A15A", "accent": "#E5484D"}),
    )
    return vehicle_id


async def _items(su: asyncpg.Connection, run_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await su.fetch(
        """select c.id, c.status, c.concept, c.rejection_reason,
                  c.brief->>'template_key' as template,
                  array_agg(distinct p.locale) filter (where p.locale is not null) as locales,
                  array_agg(distinct a.aspect_ratio) filter (where a.id is not null) as ratios,
                  string_agg(p.caption, ' || ') as captions
             from content_items c
             left join content_copy p on p.content_item_id = c.id
             left join content_assets a on a.content_item_id = c.id
            where c.run_id = $1 group by c.id""",
        run_id,
    )
    return [dict(r) for r in rows]


#: The run, kept across tests. A module-scoped async fixture would need a
#: module-scoped loop, which the function-scoped `db` fixture cannot share — so
#: the memo is here instead. Without it these six assertions are six full runs:
#: about a hundred and fifty model calls to answer six questions about one.
_RESULT: Produced | None = None


@pytest.fixture
async def produced(db: None, seeded: None, su: asyncpg.Connection, stored: list[str]) -> Produced:
    """One real run, shared by every assertion."""
    global _RESULT
    if _RESULT is not None:
        return _RESULT
    objective = "This Patrol has been sitting for 75 days. Move it."
    vehicle_id = await _seed(su)
    run_id = await planner.create_run(
        tenant_id=TENANT_A,
        goal=objective,
        tasks=[
            PlannedTask(
                task_key="plan",
                agent="content_strategist",
                input={
                    "vehicle_ids": [str(vehicle_id)],
                    "objective": objective,
                    "count": PIECES,
                    "locales": ["en", "ar"],
                },
            )
        ],
        autonomy="autopilot",
    )
    await execute_run(TENANT_A, run_id)
    await compositor.close_browser()
    _RESULT = (await _items(su, run_id), run_id)
    return _RESULT


async def test_one_vehicle_yields_a_week_of_content(produced: Produced) -> None:
    """The plan's acceptance: at least eight pieces from one well-photographed
    car."""
    items, _ = produced
    assert len(items) >= PIECES, f"only {len(items)} pieces planned"


async def test_every_piece_is_written_in_both_languages(produced: Produced) -> None:
    items, _ = produced
    missing = [i["concept"] for i in items if sorted(i["locales"] or []) != ["ar", "en"]]
    assert not missing, f"pieces missing a language: {missing}"


async def test_every_piece_survives_its_own_guards(produced: Produced) -> None:
    """The one that matters. A caption quoting a price the database does not
    hold is this product's zero-tolerance failure, and the model writes the
    captions."""
    items, _ = produced
    rejected = [
        f"{i['concept']}: {i['rejection_reason']}"
        for i in items
        if i["status"] != "pending_approval"
    ]
    assert not rejected, "guards rejected: " + " | ".join(rejected)


async def test_every_piece_renders_every_ratio_its_template_declares(
    produced: Produced,
) -> None:
    items, _ = produced
    for item in items:
        expected = set(compositor.manifest(item["template"]).aspect_ratios)
        assert set(item["ratios"] or []) == expected, f"{item['concept']} rendered {item['ratios']}"


async def test_the_plan_is_a_mix_not_eight_of_the_same_thing(produced: Produced) -> None:
    """Eight hero posts about one car is one post and seven duplicates."""
    items, _ = produced
    concepts = [i["concept"] for i in items]
    assert len(set(concepts)) >= 4, f"only {len(set(concepts))} distinct concepts: {concepts}"
    assert concepts.count("hero") <= 2


async def test_no_caption_invents_a_price(produced: Produced) -> None:
    """Belt and braces over the guard: the only figure that may appear is the
    one in the record."""
    items, _ = produced
    for item in items:
        for wrong in ("295,000", "299,000", "320,000", "31,000,000"):
            assert wrong not in (item["captions"] or ""), f"{item['concept']} quoted {wrong}"
