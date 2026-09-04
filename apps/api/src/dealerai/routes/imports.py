"""CSV import: propose a mapping, then import under a confirmed one.

Two endpoints and a rule between them. `/preview` returns a *proposal*;
`/` requires a `mapping` in the request body and never consults the proposal.
The confirmation is therefore structural rather than a promise in a docstring:
there is no code path from a model's guess to a written row that does not pass
through something a human posted back.

The file is uploaded to both. That is deliberate — the alternative is holding a
half-imported spreadsheet server-side with an expiry job, a cleanup task and a
new way to leak one tenant's file to another, all to save one upload of a file
the browser already has.

Separate module from vehicles.py because `inventory` imports VehicleCreate from
there; putting these routes beside it would make the cycle.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

import asyncpg
import structlog
from fastapi import APIRouter, Depends, File, Form, UploadFile

from .. import inventory
from ..core.errors import Unusable
from ..db.session import tenant_session
from ..deps import TenantContext, require_role
from ..events.bus import emit
from .vehicles import VehicleCreate

log = structlog.get_logger()

router = APIRouter(prefix="/v1/vehicles/import", tags=["vehicles"])

Marketer = Annotated[TenantContext, Depends(require_role("marketer"))]

#: A stock list is a text file. 20MB is a very large one, and the limit exists
#: so a mistaken upload fails on arrival rather than in the CSV reader.
MAX_BYTES = 20 * 1024 * 1024


async def _rows(file: UploadFile) -> tuple[list[str], list[dict[str, str]]]:
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise Unusable(f"file is larger than {MAX_BYTES // 1024 // 1024}MB")
    try:
        return inventory.read_rows(inventory.decode(raw))
    except ValueError as exc:
        raise Unusable(str(exc)) from exc


@router.post("/preview")
async def preview(ctx: Marketer, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    """Read the file and guess what each column is.

    Nothing is written. The response is what the confirmation screen renders,
    including the sample rows — a mapping is far easier to check against three
    real rows than against a column name.
    """
    headers, rows = await _rows(file)
    proposal = await inventory.propose_mapping(
        tenant_id=ctx.tenant_id, headers=headers, sample=rows
    )
    return {
        "headers": headers,
        "row_count": len(rows),
        "sample": rows[: inventory.SAMPLE_ROWS],
        "mapping": proposal.as_dict(),
        "fields": sorted(inventory.MAPPABLE),
    }


@router.post("", response_model=inventory.ImportResult)
async def run_import(
    ctx: Marketer,
    file: Annotated[UploadFile, File()],
    mapping: Annotated[str, Form(description='confirmed {"header": "field"} JSON')],
) -> inventory.ImportResult:
    """Import under the mapping the human confirmed.

    Rows are inserted one at a time, each in its own transaction. A single
    statement would be faster and would also mean row 12's duplicate VIN throws
    away the other 49 — which is the behaviour this endpoint exists to avoid.
    """
    headers, rows = await _rows(file)
    try:
        confirmed = json.loads(mapping)
    except json.JSONDecodeError as exc:
        raise Unusable("mapping is not valid JSON") from exc
    if not isinstance(confirmed, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in confirmed.items()
    ):
        raise Unusable("mapping must be an object of header -> field")

    unknown = set(confirmed.values()) - inventory.MAPPABLE
    if unknown:
        raise Unusable(f"not importable fields: {', '.join(sorted(unknown))}")
    if "make" not in confirmed.values() or "model" not in confirmed.values():
        raise Unusable("the mapping must include make and model")

    vehicles, errors = inventory.rows_to_vehicles(confirmed, rows)
    created = 0
    for number, vehicle in vehicles:
        try:
            await _insert(ctx, vehicle)
            created += 1
        except asyncpg.UniqueViolationError:
            # Reported against its row, like every other failure. "A duplicate
            # VIN exists somewhere in your file" is not an actionable message.
            errors.append(
                inventory.RowError(
                    row=number,
                    message=f"duplicate stock number or VIN: {vehicle.stock_number or vehicle.vin}",
                )
            )
    errors.sort(key=lambda e: e.row)

    log.info(
        "csv_import",
        tenant_id=str(ctx.tenant_id),
        headers=len(headers),
        created=created,
        failed=len(errors),
    )
    return inventory.ImportResult(created=created, errors=errors)


async def _insert(ctx: TenantContext, vehicle: VehicleCreate) -> None:
    fields = vehicle.model_dump()
    names = ["tenant_id", "source", *fields]
    values: list[Any] = [ctx.tenant_id, "csv", *fields.values()]
    placeholders = ", ".join(f"${i + 1}" for i in range(len(values)))
    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        row = await conn.fetchrow(
            f"insert into vehicles ({', '.join(names)}) "  # noqa: S608
            f"values ({placeholders}) returning id",
            *values,
        )
        await emit(conn, "vehicle.created", {"vehicle_id": str(row["id"])}, tenant_id=ctx.tenant_id)
