from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..core.errors import Conflict, Forbidden, NotFound
from ..db.session import tenant_session
from ..deps import ROLES, Ctx
from ..events.bus import emit
from ..orchestrator.approvals import approver_role

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])

Status = Literal["pending", "approved", "rejected", "expired"]


class ApprovalOut(BaseModel):
    id: UUID
    kind: str
    summary: str
    payload: dict[str, Any]
    status: Status
    entity_type: str | None = None
    entity_id: UUID | None = None
    run_id: UUID | None = None
    expires_at: datetime | None = None
    created_at: datetime
    decided_at: datetime | None = None
    decision_note: str | None = None
    #: What role is needed to decide this one. The UI hides what you cannot act on.
    required_role: str


class Decision(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class BulkDecision(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=100)
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=1000)


class BulkResult(BaseModel):
    decided: list[UUID]
    skipped: dict[str, str]


_COLUMNS = """
    id, kind, summary, payload, status, entity_type, entity_id, run_id, task_id,
    expires_at, created_at, decided_at, decision_note
"""


def _present(row: Any) -> dict[str, Any]:
    """Expiry is computed on read rather than swept by a job.

    A pending approval past its TTL is expired the moment anyone looks. A cron
    that flips the column would be a second source of truth for the same fact.
    """
    data = dict(row)
    if (
        data["status"] == "pending"
        and data["expires_at"] is not None
        and data["expires_at"] < datetime.now(UTC)
    ):
        data["status"] = "expired"
    data["required_role"] = approver_role(data["kind"])
    return data


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    ctx: Ctx,
    status: Status = "pending",
    limit: int = Query(default=50, le=200),
) -> list[dict[str, Any]]:
    async with tenant_session(ctx.tenant_id) as conn:
        rows = await conn.fetch(
            f"""select {_COLUMNS} from approvals
                where tenant_id = $1
                order by created_at desc
                limit $2""",  # noqa: S608 - column list is a module constant
            ctx.tenant_id,
            limit,
        )
    return [a for a in map(_present, rows) if a["status"] == status]


@router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(approval_id: UUID, ctx: Ctx) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id) as conn:
        row = await conn.fetchrow(
            f"select {_COLUMNS} from approvals where id = $1",  # noqa: S608
            approval_id,
        )
    if row is None:
        raise NotFound("no such approval")
    return _present(row)


async def _decide(
    approval_id: UUID,
    ctx: Ctx,
    outcome: Literal["approved", "rejected"],
    note: str | None,
) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        # FOR UPDATE so two people clicking Approve at once cannot both win and
        # publish the same content twice.
        row = await conn.fetchrow(
            f"select {_COLUMNS} from approvals where id = $1 for update",  # noqa: S608
            approval_id,
        )
        if row is None:
            raise NotFound("no such approval")

        current = _present(row)
        required = current["required_role"]
        if ROLES.index(ctx.role) < ROLES.index(required):
            raise Forbidden(f"deciding a {current['kind']!r} approval requires the {required} role")
        if current["status"] == "expired":
            raise Conflict("this approval expired and can no longer be decided")
        if current["status"] != "pending":
            raise Conflict(f"already {current['status']}")

        updated = await conn.fetchrow(
            f"""update approvals
                   set status = $2, decided_by = $3, decided_at = now(), decision_note = $4
                 where id = $1
             returning {_COLUMNS}""",  # noqa: S608
            approval_id,
            outcome,
            ctx.user.id,
            note,
        )
        # Emitted in the same transaction as the decision, and carrying the
        # task id: events/handlers/runs.py resumes exactly that branch of the
        # run's DAG, and an approval that names no task simply resumes nothing.
        await emit(
            conn,
            "approval.decided",
            {
                "approval_id": str(approval_id),
                "kind": current["kind"],
                "decision": outcome,
                "run_id": str(current["run_id"]) if current["run_id"] else None,
                "task_id": str(current["task_id"]) if current["task_id"] else None,
            },
            tenant_id=ctx.tenant_id,
            dedupe_key=f"approval-decided:{approval_id}",
            priority=5,
        )
    return _present(updated)


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
async def approve(approval_id: UUID, body: Decision, ctx: Ctx) -> dict[str, Any]:
    return await _decide(approval_id, ctx, "approved", body.note)


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject(approval_id: UUID, body: Decision, ctx: Ctx) -> dict[str, Any]:
    return await _decide(approval_id, ctx, "rejected", body.note)


@router.post("/bulk", response_model=BulkResult)
async def decide_bulk(body: BulkDecision, ctx: Ctx) -> BulkResult:
    """Clear a morning's queue in one click.

    Partial success is the expected outcome, not an error: one already-decided
    or expired item must not sink the other forty-nine. Each skip says why.
    """
    decided: list[UUID] = []
    skipped: dict[str, str] = {}
    for approval_id in body.ids:
        try:
            await _decide(approval_id, ctx, body.decision, body.note)
            decided.append(approval_id)
        except (Conflict, NotFound, Forbidden) as exc:
            skipped[str(approval_id)] = exc.detail or exc.title
    return BulkResult(decided=decided, skipped=skipped)
