"""Inventory event handlers. See docs/05-workflows.md § W2."""

from __future__ import annotations

from uuid import UUID

import structlog

from ...agents.content import enrichment
from ...db.session import tenant_session
from ...media import storage, vision
from ..bus import Event, emit, handler

log = structlog.get_logger()


@handler("vehicle.media_uploaded")
async def on_media_uploaded(event: Event) -> None:
    """Assess every unassessed photo on a vehicle, then rank them.

    Ranking runs over the whole set, so it happens after all the per-photo
    calls rather than inside them — a photo cannot know whether it is the best
    front three-quarter without seeing the others.

    Idempotent: photos already carrying a quality_score are skipped, so a retry
    after a partial failure costs only the photos that did not finish.
    """
    tenant_id = event.tenant_id
    vehicle_id = UUID(event.payload["vehicle_id"])
    if tenant_id is None:
        raise ValueError("vehicle.media_uploaded requires a tenant")

    async with tenant_session(tenant_id) as conn:
        rows = await conn.fetch(
            """select id, storage_path, mime, quality_score
               from vehicle_media
               where vehicle_id = $1 and kind = 'photo'
               order by created_at""",
            vehicle_id,
        )

    if not rows:
        log.info("no_photos_to_assess", vehicle_id=str(vehicle_id))
        return

    assessments: dict[UUID, vision.PhotoAssessment] = {}
    for row in rows:
        if row["quality_score"] is not None:
            async with tenant_session(tenant_id) as conn:
                stored = await conn.fetchval(
                    "select qa from vehicle_media where id = $1", row["id"]
                )
            if stored:
                assessments[row["id"]] = vision.PhotoAssessment.model_validate(stored)
                continue

        image = await storage.download(row["storage_path"])
        assessment = await vision.assess_photo(
            tenant_id=tenant_id,
            image=image,
            mime_type=row["mime"] or "image/jpeg",
        )
        assessments[row["id"]] = assessment

        async with tenant_session(tenant_id) as conn:
            await conn.execute(
                """update vehicle_media
                      set angle = $2, quality_score = $3, qa = $4
                    where id = $1""",
                row["id"],
                assessment.angle,
                round(assessment.quality_score, 2),
                assessment.model_dump(),
            )

    ranked = vision.rank(assessments)

    async with tenant_session(tenant_id) as conn, conn.transaction():
        # Clear first: a vehicle whose old hero was just rejected must not keep
        # two heroes for the instant between the two updates.
        await conn.execute(
            "update vehicle_media set is_hero = false where vehicle_id = $1", vehicle_id
        )
        for photo in ranked:
            await conn.execute(
                "update vehicle_media set is_hero = $2, sort_order = $3 where id = $1",
                photo.media_id,
                photo.is_hero,
                photo.sort_order,
            )
        await emit(
            conn,
            "vehicle.photos_assessed",
            {
                "vehicle_id": str(vehicle_id),
                "assessed": len(ranked),
                "usable": sum(1 for p in ranked if not p.assessment.rejected),
                "has_hero": any(p.is_hero for p in ranked),
            },
            tenant_id=tenant_id,
        )

    log.info(
        "photos_assessed",
        vehicle_id=str(vehicle_id),
        total=len(ranked),
        rejected=sum(1 for p in ranked if p.assessment.rejected),
        hero=next((str(p.media_id) for p in ranked if p.is_hero), None),
    )


@handler("vehicle.created")
async def on_vehicle_created(event: Event) -> None:
    """Normalise, enrich from the tenant's documents, extract selling points.

    Emits `vehicle.ready` whatever the enrichment found — including nothing.
    A car with a thin record is still a car the dealer wants marketed; the
    downstream strategist reads what is there and works with it. Blocking
    `vehicle.ready` on a full spec sheet would silently strand every vehicle
    imported from a messy CSV, which is most of them.
    """
    tenant_id = event.tenant_id
    if tenant_id is None:
        raise ValueError("vehicle.created requires a tenant")
    vehicle_id = UUID(event.payload["vehicle_id"])

    verified = await enrichment.enrich(tenant_id=tenant_id, vehicle_id=vehicle_id)

    async with tenant_session(tenant_id) as conn:
        await emit(
            conn,
            "vehicle.ready",
            {
                "vehicle_id": str(vehicle_id),
                "filled": sorted(verified.updates),
                "usps": len(verified.usps),
            },
            tenant_id=tenant_id,
            dedupe_key=f"vehicle.ready:{vehicle_id}",
        )
