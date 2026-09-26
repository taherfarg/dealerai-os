"""The Image Agent: composites the piece, then decides whether it may exist.

No model call. It fills a template with the copy the Copywriter wrote and the
photograph the Creative Director chose, renders every ratio, and runs the
guards over the finished thing.

**The guards run here because this is the last place before an asset exists.**
The copywriter checks brand rules as it writes, which is helpful and is not
enforcement — it is a model checking itself. Price and inventory are checked
only here, over the exact words that will be published, against the database as
it is now rather than as it was when the run started forty seconds ago.

A piece that fails is left as a draft with the reasons attached. Nobody's work
is thrown away and nobody's wrong price is published.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID

import structlog
from pydantic import BaseModel, Field

from ...ai.models import TaskKind
from ...core.money import exponent
from ...db.session import tenant_session
from ...guards import Finding
from ...guards import brand as brand_guard
from ...guards import inventory as inventory_guard
from ...guards import price as price_guard
from ...media import compositor, storage
from ...orchestrator.gate import Action
from .. import base
from .copywriter import _brand, _rules

log = structlog.get_logger()

#: Rendering every ratio a template declares. A dealer who wants a story from a
#: post should not need a second run, and the marginal cost of another ratio is
#: 100ms of browser time.
ALL_RATIOS = True


class Input(BaseModel):
    content_item_id: str | None = None
    template_key: str | None = None
    photo_path: str | None = None
    ratios: list[str] = Field(default_factory=list)
    vehicle: dict[str, Any] = Field(default_factory=dict)
    concept: str = "hero"
    angle: str = ""
    from_tasks: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Output(BaseModel):
    content_item_id: str
    assets: list[dict[str, Any]] = Field(default_factory=list)
    locales: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


class ImageAgent:
    name: ClassVar[str] = "image_agent"
    input_schema: ClassVar[type[BaseModel]] = Input
    output_schema: ClassVar[type[BaseModel]] = Output
    #: No model call anywhere in this agent. Composition is deterministic,
    #: which is the whole reason a poster shows the car the dealer owns.
    task_kind: ClassVar[TaskKind | None] = None
    action: ClassVar[Action | None] = None

    async def run(self, inp: Input, ctx: base.AgentContext) -> base.AgentResult:
        direction, copies = _split(inp)
        item_id = inp.content_item_id or direction.get("content_item_id")
        template_key = inp.template_key or direction.get("template_key")
        if not item_id or not template_key:
            return base.AgentResult(
                status="failed", reason="no content item or template reached the image agent"
            )
        if not copies:
            return base.AgentResult(status="failed", reason="no copy reached the image agent")

        vehicle = inp.vehicle or direction.get("vehicle") or {}
        photo_path = inp.photo_path or direction.get("photo_path")

        findings = await _guard(ctx, vehicle, copies)
        if findings:
            await _reject(ctx, UUID(str(item_id)), findings)
            # A guard rejection is not an agent failure. The agent did its job
            # and the answer is no, which the run reports as a piece needing
            # attention rather than as something that broke.
            return base.AgentResult(
                status="escalated",
                reason="; ".join(f.message for f in findings)[:2000],
                output=Output(
                    content_item_id=str(item_id),
                    problems=[f.message for f in findings],
                    locales=sorted(copies),
                ).model_dump(),
            )

        brand = compositor.Brand.from_profile(await _brand_profile(ctx.tenant_id))
        photo = await _photo_uri(photo_path)
        assets: list[dict[str, Any]] = []
        ratios = inp.ratios or list(compositor.manifest(template_key).aspect_ratios)

        for locale, copy in sorted(copies.items()):
            slots = _slots(copy, vehicle, photo)
            rendered = await compositor.render(
                template_key, slots, ratios=ratios, brand=brand, locale=locale
            )
            for shot in rendered:
                path = await _store(ctx, shot)
                assets.append(
                    {
                        "aspect_ratio": shot.ratio,
                        "storage_path": path,
                        "width": shot.width,
                        "height": shot.height,
                        "bytes": len(shot.png),
                        "locale": locale,
                        "ms": shot.ms,
                    }
                )

        await _save(ctx, UUID(str(item_id)), template_key, assets)
        log.info(
            "creative_produced",
            content_item=str(item_id),
            template=template_key,
            assets=len(assets),
            locales=sorted(copies),
        )
        return base.AgentResult(
            status="ok",
            output=Output(
                content_item_id=str(item_id), assets=assets, locales=sorted(copies)
            ).model_dump(),
            artifacts=(base.ArtifactRef(kind="content_item", id=UUID(str(item_id))),),
            events=(
                base.EventSpec(
                    "content.rendered",
                    {"content_item_id": str(item_id), "assets": len(assets)},
                    dedupe_key=f"rendered:{item_id}",
                ),
            ),
        )


def _split(inp: Input) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Sort the upstream outputs into the direction and the copy per locale.

    `from_tasks` arrives keyed by task, and a task key is not a locale — the
    copy says which language it is, which is the only thing that survives a
    renamed task.
    """
    direction: dict[str, Any] = {}
    copies: dict[str, dict[str, Any]] = {}
    for output in inp.from_tasks.values():
        if not isinstance(output, dict):
            continue
        if output.get("template_key"):
            direction = output
        elif output.get("locale") and output.get("caption"):
            copies[str(output["locale"])] = output
    return direction, copies


def _slots(copy: dict[str, Any], vehicle: dict[str, Any], photo: str) -> dict[str, str]:
    price = ""
    if vehicle.get("price_minor") is not None:
        currency = vehicle.get("currency") or "AED"
        major = int(vehicle["price_minor"]) / (10 ** exponent(currency))
        price = f"{currency} {major:,.0f}"
    return {
        "photo_url": photo,
        "left_photo_url": photo,
        "right_photo_url": photo,
        "headline": copy.get("headline") or copy.get("hook") or "",
        "subhead": copy.get("subhead") or "",
        "body": copy.get("caption") or "",
        "cta": copy.get("cta") or "",
        "price": price,
        "eyebrow": str(vehicle.get("model_year") or ""),
        "badge": str(vehicle.get("vehicle_condition") or ""),
        "index": "",
        "spec_1_label": "Engine",
        "spec_1_value": str(vehicle.get("engine") or ""),
        "spec_2_label": "Power",
        "spec_2_value": f"{vehicle['power_hp']} hp" if vehicle.get("power_hp") else "",
        "spec_3_label": "Mileage",
        "spec_3_value": f"{vehicle['mileage_km']:,} km" if vehicle.get("mileage_km") else "",
        "spec_4_label": "Year",
        "spec_4_value": str(vehicle.get("model_year") or ""),
        "disclaimer": "",
    }


async def _guard(
    ctx: base.AgentContext, vehicle: dict[str, Any], copies: dict[str, dict[str, Any]]
) -> list[Finding]:
    """Price, inventory and brand, over the words that will actually publish.

    The vehicle's status is re-read from the database rather than trusted from
    the brief: a car can sell while a run is in flight, and the whole point of
    checking here is that this is the last moment before an asset exists.
    """
    findings: list[Finding] = []
    profile = await _brand_profile(ctx.tenant_id)
    allowed = set()
    status = str(vehicle.get("status") or "unknown")
    reference = str(vehicle.get("stock_number") or vehicle.get("id") or "this vehicle")

    if vehicle.get("id"):
        async with tenant_session(ctx.tenant_id) as conn:
            row = await conn.fetchrow(
                "select status, price_minor, currency, stock_number from vehicles where id = $1",
                UUID(str(vehicle["id"])),
            )
        if row is None:
            return [Finding("inventory", f"vehicle {reference} no longer exists", reference)]
        status = row["status"]
        reference = row["stock_number"] or reference
        if row["price_minor"] is not None:
            allowed.add(Decimal(row["price_minor"]) / (10 ** exponent(row["currency"])))

    findings += inventory_guard.check({reference: status})
    for locale, copy in sorted(copies.items()):
        text = " ".join(
            str(copy.get(k) or "") for k in ("headline", "subhead", "hook", "caption", "cta")
        )
        # Rules per locale: the approved CTAs for Arabic are not the ones for
        # English, and checking against the wrong list blocks every piece.
        rules = _rules(profile, locale)
        for finding in price_guard.check(text, allowed=allowed) + brand_guard.check(text, rules):
            findings.append(Finding(finding.guard, f"[{locale}] {finding.message}", finding.detail))
    return findings


async def _brand_profile(tenant_id: UUID) -> dict[str, Any]:
    profile = await _brand(tenant_id)
    async with tenant_session(tenant_id) as conn:
        row = await conn.fetchrow(
            "select colors, typography from brand_profiles where tenant_id = $1", tenant_id
        )
    return {**profile, **(dict(row) if row else {})}


async def _photo_uri(storage_path: str | None) -> str:
    """The photograph as a data URI.

    Inlined rather than linked: the browser has no credentials for a private
    bucket, and a signed URL would put an expiring secret inside a document we
    keep. A photo that cannot be fetched renders as an empty frame, which the
    scrim already handles.
    """
    if not storage_path:
        return ""
    try:
        data = await storage.download(storage_path)
    except Exception as exc:  # noqa: BLE001 - a missing photo is not a failed render
        log.warning("photo_unavailable", path=storage_path, error=str(exc))
        return ""
    import base64

    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


async def _store(ctx: base.AgentContext, shot: compositor.Rendered) -> str:
    path = storage.object_path(ctx.tenant_id, "creative", "png")
    try:
        return await storage.upload(path, shot.png, content_type="image/png")
    except Exception as exc:  # noqa: BLE001
        # The render succeeded and the bucket did not. Recording the intended
        # path keeps the row honest about what is missing instead of pretending
        # an asset exists.
        log.error("creative_upload_failed", path=path, error=str(exc))
        raise


async def _save(
    ctx: base.AgentContext, item_id: UUID, template_key: str, assets: list[dict[str, Any]]
) -> None:
    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        for order, asset in enumerate(assets):
            await conn.execute(
                """insert into content_assets
                     (tenant_id, content_item_id, aspect_ratio, storage_path, mime,
                      width, height, bytes, render_meta, sort_order)
                   values ($1,$2,$3,$4,'image/png',$5,$6,$7,$8,$9)""",
                ctx.tenant_id,
                item_id,
                asset["aspect_ratio"],
                asset["storage_path"],
                asset["width"],
                asset["height"],
                asset["bytes"],
                {"template_key": template_key, "locale": asset["locale"], "ms": asset["ms"]},
                order,
            )
        await conn.execute(
            "update content_items set status = 'pending_approval' where id = $1", item_id
        )


async def _reject(ctx: base.AgentContext, item_id: UUID, findings: list[Finding]) -> None:
    async with tenant_session(ctx.tenant_id) as conn:
        await conn.execute(
            """update content_items
                  set status = 'rejected', rejection_reason = $2
                where id = $1""",
            item_id,
            "; ".join(f.message for f in findings)[:1000],
        )


base.register(ImageAgent())
