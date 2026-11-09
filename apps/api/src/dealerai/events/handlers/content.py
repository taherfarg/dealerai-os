"""W4 — a scheduled piece goes out when its slot is due (T4.3).

Every few seconds the worker books `content.publish_due` for each piece whose
slot has come (`book_due`); scheduling it on the calendar booked nothing. The
handler checks the piece may still go out — the car still for sale, still at
the price its words and images give — then publishes it to every connected
Instagram and Facebook account at once, each its own `publications` row: one
refusing it does not stop the other. A failure that may pass is tried again,
three times in all; one that cannot is the row's, with its cause. A piece is
`published` when one channel took it, `failed` when none did.

Written here, not as an agent: publishing calls no model, and agents may not
reach connectors (tests/test_import_contracts.py).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import asyncpg
import structlog

from ... import schedule
from ...connectors.base import (
    InsightWindow,
    MediaAsset,
    NotSupported,
    OutsideMessagingWindow,
    PublishKind,
    PublishRequest,
    PublishResult,
    RateLimited,
    RequestRejected,
    TokenExpired,
)
from ...connectors.channels import social_for_channel
from ...connectors.crypto import CredentialsCorrupt
from ...core.money import Money
from ...core.words import Words, named, same
from ...db.session import system_session, tenant_session
from ...lifecycle import deals, pricing
from ...media.links import url_for
from ...orchestrator.gate import in_quiet_hours
from ...sales.clock import zone
from ..bus import Event, emit, handler
from .lifecycle import CONTENT_OWNERS, _members
from .notify import notify

log = structlog.get_logger()

#: Where a piece is published. WhatsApp is a conversation, not a feed.
PUBLISHING = ("instagram", "facebook")
#: How often the worker looks for what is due: a piece goes out within this
#: (and a worker poll) of its slot. The acceptance is a minute.
DUE_EVERY_SECONDS = 15
#: Tries per channel before its publication fails for good (W4: retry ×3).
ATTEMPTS = 3
#: The wait before the next try, doubled each time.
RETRY_SECONDS = 30
#: Instagram's caption limit, the tighter of the two.
CAPTION_LIMIT = 2_200
#: When a publication's numbers are read, after it went out (W4).
METRIC_WINDOWS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
#: The images each kind publishes, best first.
RATIOS: dict[str, tuple[str, ...]] = {
    "post": ("4:5", "1:1"),
    "carousel": ("4:5", "1:1"),
    "story": ("9:16",),
    "reel": ("9:16",),
}
#: Failures a retry cannot change: the platform said no, cannot, or needs a person.
LASTING = (TokenExpired, NotSupported, RequestRejected, OutsideMessagingWindow, CredentialsCorrupt)


# --------------------------------------------------------------------------
# the words and the pictures — pure
# --------------------------------------------------------------------------


def caption(copies: Sequence[Mapping[str, Any]], order: Sequence[str]) -> str:
    """Every language's words, the dealer's first language first, and the
    hashtags once at the end. Over Instagram's limit, the first language alone.
    ponytail: one post in every language; a post per language per account is
    a choice the dealer has not been asked for."""
    ranked = sorted(
        copies,
        key=lambda c: order.index(c["locale"]) if c["locale"] in order else len(order),
    )
    texts = [
        "\n\n".join(part for part in (c["hook"], c["caption"], c["cta"]) if part) for c in ranked
    ]
    texts = [text for text in texts if text]
    tags = list(dict.fromkeys(f"#{tag}" for c in ranked for tag in c["hashtags"] or []))
    tail = "\n\n" + " ".join(tags) if tags else ""
    whole = "\n\n".join(texts) + tail
    if len(whole) <= CAPTION_LIMIT or len(texts) < 2:
        return whole[:CAPTION_LIMIT]
    return (texts[0] + tail)[:CAPTION_LIMIT]


def images(
    assets: Sequence[Mapping[str, Any]], kind: str, locale: str | None
) -> tuple[PublishKind, list[Mapping[str, Any]]]:
    """The images in the first language, at the ratio the kind wants. A
    carousel with one image is a post."""
    mine = [a for a in assets if a["locale"] in (locale, None)] or list(assets)
    for ratio in RATIOS.get(kind, ()):
        chosen = [a for a in mine if a["aspect_ratio"] == ratio]
        if not chosen:
            continue
        if kind == "carousel":
            return ("carousel", chosen) if len(chosen) > 1 else ("post", chosen[:1])
        return cast(PublishKind, kind), chosen[:1]
    return cast(PublishKind, kind), []


def later(now: datetime, rules: schedule.Rules, tz: ZoneInfo) -> datetime:
    """An hour on, or the end of quiet hours if that lands inside them.
    ponytail: the daily limit is not consulted; one moved post can make a day
    one over."""
    moved = (now + timedelta(hours=1)).astimezone(tz)
    if rules.quiet and in_quiet_hours(moved.time(), *rules.quiet):
        end = rules.quiet[1]
        ends = moved.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
        moved = ends if ends > moved else ends + timedelta(days=1)
    return moved


def backoff(attempts: int, error: BaseException) -> timedelta:
    if isinstance(error, RateLimited):
        return timedelta(seconds=error.retry_after_seconds)
    return timedelta(seconds=RETRY_SECONDS * 2 ** max(attempts - 1, 0))


def cause(error: BaseException) -> str:
    return (str(error) or type(error).__name__)[:500]


# --------------------------------------------------------------------------
# what is due
# --------------------------------------------------------------------------


async def book_due() -> int:
    """Every piece whose slot has come, across every dealer, booked to go out.

    The dedupe key is the slot, so a pass that finds a piece already booked
    adds nothing, and a piece dragged to another slot is booked again when
    that one comes. `events` has no RLS, so a session with no tenant writes it.
    """
    async with system_session() as conn:
        rows = await conn.fetch("select tenant_id, id, scheduled_at from app.content_due()")
        for row in rows:
            slot = row["scheduled_at"].isoformat()
            await emit(
                conn,
                "content.publish_due",
                {"content_item_id": str(row["id"]), "slot": slot},
                tenant_id=row["tenant_id"],
                dedupe_key=f"publish:{row['id']}:{slot}",
                priority=2,
            )
    return len(rows)


_ITEM = """
select c.id, c.kind, c.status, c.scheduled_at, c.vehicle_id,
       v.status as vehicle_status, v.price_minor, v.currency,
       nullif(concat_ws(' ', v.model_year, v.make, v.model), '') as car,
       t.timezone, t.locales, t.autonomy_rules
  from content_items c
  join tenants t on t.id = c.tenant_id
  left join vehicles v on v.id = c.vehicle_id
 where c.id = $1
   for update of c
"""

#: Publications still to go: new, waiting their next try, or cut off mid-way
#: by a worker that died (the idempotency key keeps that from posting twice).
_GOING = """
update publications p
   set status = 'publishing', attempts = p.attempts + 1, updated_at = now()
  from channels ch
 where p.content_item_id = $1 and ch.id = p.channel_id
   and p.status in ('pending', 'publishing')
returning p.id, p.attempts, ch.platform, ch.external_id, ch.credentials
"""


@dataclass(frozen=True, slots=True)
class Going:
    kind: PublishKind
    assets: list[MediaAsset]
    caption: str
    targets: list[asyncpg.Record]


async def _tell(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    item_id: UUID,
    title: Words,
    body: Words,
    *,
    kind: str = "publish_failed",
    dedupe_key: str,
) -> None:
    for user_id in await _members(conn, tenant_id, CONTENT_OWNERS):
        await notify(
            conn,
            tenant_id=tenant_id,
            user_id=user_id,
            kind=kind,
            title=title,
            body=body,
            entity={"type": "content", "id": str(item_id)},
            dedupe_key=dedupe_key,
        )


async def _preflight(conn: asyncpg.Connection, tenant_id: UUID, item: asyncpg.Record) -> bool:
    """True when the piece must not go out, having stopped it and said why.

    The lifecycle's own checks, asked again at the last moment: a car can sell,
    or its price move, between the event that would have stopped the piece and
    the slot. Stopping one stops every piece about the car that has the same
    problem, as the lifecycle would have.
    ponytail: a piece at an old price is stopped, not made again; regenerating
    it is the content run's, from the vehicle.
    """
    vehicle_id, car = item["vehicle_id"], item["car"] or "car"
    if vehicle_id is None:
        return False
    state = item["vehicle_status"]
    if state in deals.OFF_SALE:
        await deals.stop_marketing(conn, vehicle_id, state)
        await _tell(
            conn,
            tenant_id,
            item["id"],
            Words(
                f"A post about the {car} was not published: the car is {state}",
                f"لم يُنشر منشور عن {named(car)}: السيارة لم تعد معروضة للبيع",
            ),
            Words(
                "Nothing went out. It is archived with the reason.",
                "لم يُنشر شيء، وأُرشف المنشور مع السبب.",
            ),
            dedupe_key=f"publish_failed:{item['id']}",
        )
        return True
    if item["price_minor"] is not None:
        currency = item["currency"] or "AED"
        found = await pricing.stale_content(
            conn, vehicle_id, price_minor=item["price_minor"], currency=currency
        )
        if item["id"] in found["stopped"]:
            price = str(Money(item["price_minor"], currency))
            await _tell(
                conn,
                tenant_id,
                item["id"],
                Words(
                    f"A post about the {car} was not published: it quotes another price",
                    f"لم يُنشر منشور عن {named(car)}: يذكر سعرًا غير سعرها",
                ),
                Words(
                    f"The price is now {price}. Make a new piece for the car.",
                    f"السعر الآن {price}. أنشئ منشورًا جديدًا للسيارة.",
                ),
                dedupe_key=f"publish_failed:{item['id']}",
            )
            return True
    return False


async def _begin(tenant_id: UUID, item_id: UUID, slot: str | None) -> Going | None:
    """Check the piece, claim its publications, and gather what they send —
    in one transaction, which ends before anything is sent."""
    async with tenant_session(tenant_id) as conn, conn.transaction():
        item = await conn.fetchrow(_ITEM, item_id)
        if item is None or item["status"] not in ("scheduled", "publishing"):
            return None
        if item["status"] == "scheduled":
            if slot and item["scheduled_at"].isoformat() != slot:
                return None  # moved since it was booked; the new slot books itself
            if await _preflight(conn, tenant_id, item):
                return None
            channels = await conn.fetch(
                """select id from channels
                    where platform = any($1::text[]) and status = 'connected'
                    order by platform""",
                list(PUBLISHING),
            )
            if not channels:
                tz = zone(item["timezone"])
                moved = later(datetime.now(UTC), schedule.rules_of(item["autonomy_rules"]), tz)
                await conn.execute(
                    "update content_items set scheduled_at = $2 where id = $1", item_id, moved
                )
                await _tell(
                    conn,
                    tenant_id,
                    item_id,
                    Words(
                        f"No Instagram or Facebook account is connected; a post moved to "
                        f"{moved:%H:%M}",
                        f"لا يوجد حساب إنستغرام أو فيسبوك متصل؛ نُقل منشور إلى {moved:%H:%M}",
                    ),
                    Words(
                        "Connect one and it goes out at its new time.",
                        "اربط حسابًا وسيُنشر في موعده الجديد.",
                    ),
                    kind="channel_disconnected",
                    dedupe_key=f"no_channel:{moved.date().isoformat()}",
                )
                log.info("publish_moved", content_item=str(item_id), to=moved.isoformat())
                return None
            await conn.executemany(
                """insert into publications (tenant_id, content_item_id, channel_id)
                   values ($1, $2, $3) on conflict (content_item_id, channel_id) do nothing""",
                [(tenant_id, item_id, channel["id"]) for channel in channels],
            )
            await conn.execute(
                "update content_items set status = 'publishing' where id = $1", item_id
            )

        copies = await conn.fetch(
            """select locale, hook, caption, cta, hashtags from content_copy
                where content_item_id = $1""",
            item_id,
        )
        assets = await conn.fetch(
            """select aspect_ratio, storage_path, mime, render_meta ->> 'locale' as locale
                 from content_assets where content_item_id = $1 order by sort_order""",
            item_id,
        )
        order = list(item["locales"] or [])
        first = next((lang for lang in order if any(c["locale"] == lang for c in copies)), None)
        kind, chosen = images(
            assets, item["kind"], first or (copies[0]["locale"] if copies else None)
        )
        targets = await conn.fetch(_GOING, item_id)
    return Going(
        kind=kind,
        assets=[
            MediaAsset(
                url=url_for(a["storage_path"]),
                mime=a["mime"] or "image/png",
                aspect_ratio=a["aspect_ratio"],
            )
            for a in chosen
        ],
        caption=caption(copies, order),
        targets=list(targets),
    )


async def _send(going: Going, target: asyncpg.Record) -> PublishResult | BaseException:
    try:
        connector = social_for_channel(target)
        return await connector.publish(
            PublishRequest(
                kind=going.kind,
                assets=going.assets,
                caption=going.caption,
                idempotency_key=f"publication:{target['id']}",
            )
        )
    except Exception as exc:  # noqa: BLE001 - each channel's failure is its own row
        return exc


async def _finish(
    tenant_id: UUID,
    item_id: UUID,
    going: Going,
    results: Sequence[PublishResult | BaseException],
) -> None:
    retry: timedelta | None = None
    tries = 0
    async with tenant_session(tenant_id) as conn, conn.transaction():
        for target, result in zip(going.targets, results, strict=True):
            if isinstance(result, PublishResult):
                await conn.execute(
                    """update publications
                          set status = 'published', external_id = $2, permalink = $3,
                              published_at = now(), error = null, updated_at = now()
                        where id = $1""",
                    target["id"],
                    result.external_id,
                    result.permalink,
                )
                continue
            final = isinstance(result, LASTING) or target["attempts"] >= ATTEMPTS
            await conn.execute(
                """update publications set status = $2, error = $3, updated_at = now()
                    where id = $1""",
                target["id"],
                "failed" if final else "pending",
                f"{target['platform']}: {cause(result)}",
            )
            log.warning(
                "publication_failed",
                content_item=str(item_id),
                platform=target["platform"],
                attempt=target["attempts"],
                final=final,
                error=cause(result),
            )
            if not final:
                wait = backoff(target["attempts"], result)
                retry = wait if retry is None else min(retry, wait)
                tries = max(tries, target["attempts"])

        if retry is not None:
            await emit(
                conn,
                "content.publish_due",
                {"content_item_id": str(item_id)},
                tenant_id=tenant_id,
                dedupe_key=f"publish-retry:{item_id}:{tries}",
                run_after=datetime.now(UTC) + retry,
                priority=2,
            )
            return

        rows = await conn.fetch(
            """select p.status, p.error, p.published_at, ch.platform
                 from publications p join channels ch on ch.id = p.channel_id
                where p.content_item_id = $1 order by ch.platform""",
            item_id,
        )
        went = [r for r in rows if r["status"] == "published"]
        failed = [r for r in rows if r["status"] == "failed"]
        if went:
            await conn.execute(
                """update content_items set status = 'published', published_at = $2
                    where id = $1""",
                item_id,
                min(r["published_at"] for r in went),
            )
            await emit(
                conn,
                "content.published",
                {"content_item_id": str(item_id)},
                tenant_id=tenant_id,
                dedupe_key=f"published:{item_id}",
            )
        else:
            await conn.execute(
                """update content_items set status = 'failed', rejection_reason = $2
                    where id = $1""",
                item_id,
                "; ".join(r["error"] or r["platform"] for r in failed)[:1000] or "nothing went out",
            )
        if failed:
            where = ", ".join(sorted({r["platform"].title() for r in failed}))
            done = ", ".join(sorted({r["platform"].title() for r in went}))
            await _tell(
                conn,
                tenant_id,
                item_id,
                Words(
                    f"Published on {done}; {where} refused it"
                    if went
                    else f"A post did not go out on {where}",
                    f"نُشر على {done}؛ ورفضه {where}" if went else f"لم يُنشر منشور على {where}",
                ),
                # The platform's own words: data, the same in either language.
                same("; ".join(r["error"] or "" for r in failed)),
                dedupe_key=f"publish_failed:{item_id}",
            )
    log.info("content_published", content_item=str(item_id), channels=len(went), failed=len(failed))


@handler("content.publish_due")
async def on_publish_due(event: Event) -> None:
    if event.tenant_id is None:
        raise ValueError("content.publish_due requires a tenant")
    item_id = UUID(str(event.payload["content_item_id"]))
    going = await _begin(event.tenant_id, item_id, event.payload.get("slot"))
    if going is None or not going.targets:
        return
    results = await asyncio.gather(*(_send(going, target) for target in going.targets))
    await _finish(event.tenant_id, item_id, going, results)


# --------------------------------------------------------------------------
# what it did — read later (W4: +1h, +24h, +7d, +30d)
# --------------------------------------------------------------------------


@handler("content.published")
async def on_published(event: Event) -> None:
    """Each publication's numbers, booked for when they mean something."""
    if event.tenant_id is None:
        raise ValueError("content.published requires a tenant")
    item_id = UUID(str(event.payload["content_item_id"]))
    async with tenant_session(event.tenant_id) as conn, conn.transaction():
        went = await conn.fetch(
            """select id, published_at from publications
                where content_item_id = $1 and status = 'published'""",
            item_id,
        )
        for publication in went:
            for window, after in METRIC_WINDOWS.items():
                await emit(
                    conn,
                    "content.metrics_due",
                    {"publication_id": str(publication["id"]), "window": window},
                    tenant_id=event.tenant_id,
                    dedupe_key=f"metrics:{publication['id']}:{window}",
                    run_after=publication["published_at"] + after,
                )


@handler("content.metrics_due")
async def on_metrics_due(event: Event) -> None:
    """One window's numbers, once. A fetch that fails is the event's to retry,
    and a retry after one that landed writes nothing (T6.1)."""
    if event.tenant_id is None:
        raise ValueError("content.metrics_due requires a tenant")
    publication_id = UUID(str(event.payload["publication_id"]))
    window = str(event.payload["window"])
    if window not in METRIC_WINDOWS:
        raise ValueError(f"no metric window {window!r}")
    async with tenant_session(event.tenant_id) as conn:
        row = await conn.fetchrow(
            """select p.external_id as media_id, ch.platform, ch.external_id, ch.credentials,
                      exists (select 1 from content_metrics m
                               where m.publication_id = p.id and m.metric_window = $2) as read
                 from publications p join channels ch on ch.id = p.channel_id
                where p.id = $1 and p.status = 'published'""",
            publication_id,
            window,
        )
    if row is None or row["read"] or not row["media_id"]:
        return
    insights = await social_for_channel(row).get_insights(
        row["media_id"], cast(InsightWindow, window)
    )
    async with tenant_session(event.tenant_id) as conn:
        await conn.execute(
            """insert into content_metrics
                 (tenant_id, publication_id, metric_window, impressions, reach, likes, comments,
                  shares, saves, video_views, watch_time_ms, profile_visits, link_clicks, raw)
               select $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14
                where not exists (select 1 from content_metrics
                                   where publication_id = $2 and metric_window = $3)""",
            event.tenant_id,
            publication_id,
            window,
            insights.impressions,
            insights.reach,
            insights.likes,
            insights.comments,
            insights.shares,
            insights.saves,
            insights.video_views,
            insights.watch_time_ms,
            insights.profile_visits,
            insights.link_clicks,
            insights.raw,
        )
