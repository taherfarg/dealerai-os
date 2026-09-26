"""Pipelines and the stages a manager can reshape.

The stage list is replaced in one call rather than patched one stage at a time:
reordering a board with four PATCHes is how a board ends up with two stages in
position three.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..core.errors import NotFound, StageInUse, Unusable
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission

router = APIRouter(prefix="/v1/pipelines", tags=["pipelines"])

PIPELINES = """
select p.id, p.name, p.position, p.is_default,
       coalesce(
         jsonb_agg(
           jsonb_build_object('id', s.id, 'name', s.name, 'position', s.position,
                              'category', s.category)
           order by s.position, s.name
         ) filter (where s.id is not null),
         '[]'::jsonb
       ) as stages
  from pipelines p
  left join pipeline_stages s on s.pipeline_id = p.id
 where ($1::uuid is null or p.id = $1)
 group by p.id
 order by p.is_default desc, p.position, p.name
"""


class Stage(BaseModel):
    id: UUID
    name: str
    position: int
    category: Literal["open", "won", "lost"]


class Pipeline(BaseModel):
    id: UUID
    name: str
    position: int
    is_default: bool
    stages: list[Stage]


class StageIn(BaseModel):
    #: Present for a stage that already exists; absent creates one.
    id: UUID | None = None
    name: str = Field(min_length=1, max_length=60)
    category: Literal["open", "won", "lost"]


class StagesIn(BaseModel):
    stages: list[StageIn] = Field(min_length=2)


def _workable(stages: list[StageIn]) -> None:
    """The three rules a board has to satisfy, each with its own sentence.

    In the route rather than a Pydantic validator: a validator's answer is a
    400 with `{"field": "", "code": "value_error"}`, and the person reshaping
    the board needs to read which rule they broke.
    """
    categories = [stage.category for stage in stages]
    if categories.count("won") != 1:
        raise Unusable("a pipeline has exactly one won stage")
    if "lost" not in categories:
        raise Unusable("a pipeline needs somewhere to put a lost lead")
    if not categories.count("open"):
        raise Unusable("a pipeline needs at least one stage leads live in")


async def _one(conn: Any, pipeline_id: UUID) -> dict[str, Any]:
    row = await conn.fetchrow(PIPELINES, pipeline_id)
    if row is None:
        raise NotFound("no such pipeline")
    return dict(row)


@router.get("", response_model=list[Pipeline])
async def list_pipelines(ctx: Ctx) -> list[dict[str, Any]]:
    """Every board in the workspace, default first, each with its stages in order."""
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        return [dict(row) for row in await conn.fetch(PIPELINES, None)]


@router.put("/{pipeline_id}/stages", response_model=Pipeline)
async def replace_stages(
    pipeline_id: UUID,
    body: StagesIn,
    ctx: Annotated[TenantContext, Depends(require_permission("pipeline.edit_stages"))],
) -> dict[str, Any]:
    """The list as sent becomes the board, in the order it arrives.

    A stage that still holds leads cannot be deleted — moving them first is a
    decision only a person can make, and the error says how many there are.
    """
    _workable(body.stages)
    async with (
        tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn,
        conn.transaction(),
    ):
        await _one(conn, pipeline_id)
        existing = {
            row["id"]: row["name"]
            for row in await conn.fetch(
                "select id, name from pipeline_stages where pipeline_id = $1 for update",
                pipeline_id,
            )
        }
        keeping = {stage.id for stage in body.stages if stage.id}
        unknown = keeping - set(existing)
        if unknown:
            raise Unusable("one of those stages belongs to a different pipeline")

        for stage_id in set(existing) - keeping:
            held = await conn.fetchval("select count(*) from leads where stage_id = $1", stage_id)
            if held:
                raise StageInUse(
                    f"{existing[stage_id]} still holds {held} "
                    f"{'lead' if held == 1 else 'leads'}. Move them first."
                )
            await conn.execute("delete from pipeline_stages where id = $1", stage_id)

        for position, stage in enumerate(body.stages):
            if stage.id:
                await conn.execute(
                    """update pipeline_stages set name = $2, position = $3, category = $4
                        where id = $1""",
                    stage.id,
                    stage.name,
                    position,
                    stage.category,
                )
            else:
                await conn.execute(
                    """insert into pipeline_stages (tenant_id, pipeline_id, name, position,
                                                    category)
                       values ($1, $2, $3, $4, $5)""",
                    ctx.tenant_id,
                    pipeline_id,
                    stage.name,
                    position,
                    stage.category,
                )
        return await _one(conn, pipeline_id)
