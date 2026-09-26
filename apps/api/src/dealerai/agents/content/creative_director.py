"""The Creative Director: which photograph, which template, which crop.

One brief in, one design decision out, plus the `content_items` row everything
downstream attaches to.

It does not write copy and it does not render pixels. What it decides is the
thing a person would argue about in a review — the shot and the layout — and
keeping that a separate task means the argument has a trace.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal
from uuid import UUID

import structlog
from pydantic import BaseModel, Field

from ...ai.gateway import SystemLayers, complete
from ...ai.models import TaskKind
from ...ai.prompts import load
from ...db.session import tenant_session
from ...media import compositor
from ...orchestrator.gate import Action
from .. import base

log = structlog.get_logger()


class Choice(BaseModel):
    template_key: str = Field(description="Exactly one of the templates you were offered.")
    photo_index: int = Field(
        ge=0, description="Which of the offered photographs, by its number in the list."
    )
    rationale: str = Field(max_length=300)


class Input(BaseModel):
    concept: str
    vehicle_id: str
    angle: str
    kind: Literal["post", "story", "reel", "carousel"] = "post"


class Output(BaseModel):
    content_item_id: str
    template_key: str
    photo_path: str | None = None
    ratios: list[str]
    vehicle: dict[str, Any]


_VEHICLE = """
select id, make, model, trim, model_year, mileage_km, price_minor, currency, status,
       engine, power_hp, transmission, fuel, seats, exterior_color, interior_color,
       features, specs
  from vehicles where id = $1
"""

_PHOTOS = """
select storage_path, angle, quality_score, is_hero
  from vehicle_media
 where vehicle_id = $1 and kind = 'photo'
   and coalesce(qa->>'rejected', 'false') = 'false'
 order by is_hero desc, sort_order
 limit 12
"""


class CreativeDirector:
    name: ClassVar[str] = "creative_director"
    input_schema: ClassVar[type[BaseModel]] = Input
    output_schema: ClassVar[type[BaseModel]] = Output
    task_kind: ClassVar[TaskKind | None] = TaskKind.CREATIVE_DIRECTION
    action: ClassVar[Action | None] = None

    async def run(self, inp: Input, ctx: base.AgentContext) -> base.AgentResult:
        try:
            vehicle_id = UUID(inp.vehicle_id)
        except ValueError:
            return base.AgentResult(
                status="failed", reason=f"{inp.vehicle_id!r} is not a vehicle id"
            )

        async with tenant_session(ctx.tenant_id) as conn:
            vehicle = await conn.fetchrow(_VEHICLE, vehicle_id)
            photos = await conn.fetch(_PHOTOS, vehicle_id) if vehicle else []
        if vehicle is None:
            return base.AgentResult(
                status="failed", reason=f"no vehicle {inp.vehicle_id} in this dealership"
            )

        options = _templates_for(inp.concept)
        if not options:
            return base.AgentResult(
                status="failed", reason=f"no template renders the {inp.concept!r} concept"
            )

        choice = await _choose(inp, options, photos, ctx)
        cost = choice[1]
        picked = choice[0]

        template_key = picked.template_key if picked else options[0]
        photo = (
            photos[picked.photo_index]["storage_path"]
            if picked and photos and 0 <= picked.photo_index < len(photos)
            else (photos[0]["storage_path"] if photos else None)
        )

        content_item_id = await _create_item(ctx, vehicle_id, inp, template_key)
        log.info(
            "creative_directed",
            content_item=str(content_item_id),
            template=template_key,
            photo=photo,
            photos_offered=len(photos),
        )
        return base.AgentResult(
            status="ok",
            output=Output(
                content_item_id=str(content_item_id),
                template_key=template_key,
                photo_path=photo,
                ratios=list(compositor.manifest(template_key).aspect_ratios),
                vehicle={k: _plain(v) for k, v in dict(vehicle).items()},
            ).model_dump(),
            artifacts=(base.ArtifactRef(kind="content_item", id=content_item_id),),
            cost_usd=cost,
        )


def _plain(value: Any) -> Any:
    return str(value) if isinstance(value, UUID) else value


def _templates_for(concept: str) -> list[str]:
    """Templates whose manifest declares this concept's kind.

    Read from the manifests rather than a table in Python: a designer adding a
    template is supposed to be able to do it without touching this file.
    """
    from .strategist import TEMPLATES

    wanted = TEMPLATES.get(concept, ())
    available = set(compositor.keys())
    return [key for key in wanted if key in available] or [
        key for key in sorted(available) if compositor.manifest(key).kind == concept
    ]


async def _choose(
    inp: Input, options: list[str], photos: list[Any], ctx: base.AgentContext
) -> tuple[Choice | None, float]:
    """Ask for the shot and the layout. One template is not a question.

    A single option means there is nothing to decide, and paying a model to
    confirm it is a call per brief for no information.
    """
    if len(options) == 1 and len(photos) <= 1:
        return None, 0.0

    listing = "\n".join(
        f"{i}. angle={p['angle'] or 'unknown'} quality={p['quality_score'] or '?'}"
        f"{' (current hero)' if p['is_hero'] else ''}"
        for i, p in enumerate(photos)
    )
    result = await complete(
        TaskKind.CREATIVE_DIRECTION,
        tenant_id=ctx.tenant_id,
        system=SystemLayers(role=load("_rules") + "\n\n" + load("creative_director")),
        messages=(
            f"## Brief\nconcept: {inp.concept}\nformat: {inp.kind}\n"
            f"angle: <untrusted>{inp.angle}</untrusted>\n\n"
            f"## Templates you may choose\n{', '.join(options)}\n\n"
            f"## Photographs, already assessed\n{listing or 'none available'}"
        ),
        output_schema=Choice,
        run_id=ctx.run_id,
        task_id=ctx.task_id,
        trace_name="creative_director",
    )
    picked = result.parsed if isinstance(result.parsed, Choice) else None
    if picked and picked.template_key not in options:
        # It invented a template. Falling back beats failing the brief, and the
        # trace records what it asked for.
        log.warning("director_picked_unknown_template", asked=picked.template_key)
        picked = Choice(
            template_key=options[0], photo_index=picked.photo_index, rationale=picked.rationale
        )
    return picked, result.cost_usd


async def _create_item(
    ctx: base.AgentContext, vehicle_id: UUID, inp: Input, template_key: str
) -> UUID:
    async with tenant_session(ctx.tenant_id) as conn:
        item_id: UUID = await conn.fetchval(
            """insert into content_items
                 (tenant_id, vehicle_id, run_id, kind, concept, brief, status)
               values ($1,$2,$3,$4,$5,$6,'draft') returning id""",
            ctx.tenant_id,
            vehicle_id,
            ctx.run_id,
            inp.kind,
            inp.concept,
            {"angle": inp.angle, "template_key": template_key},
        )
    return item_id


base.register(CreativeDirector())
