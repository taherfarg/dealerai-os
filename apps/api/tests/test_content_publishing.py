"""T4.3: a scheduled piece goes out when its slot is due.

The acceptance is the spine of this file: a scheduled item publishes within
60 s of its slot; with Instagram succeeding and Facebook failing the item is
`published` with one `failed` publication row and a visible cause; a vehicle
marked sold cancels its scheduled items.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from typing import Any

import asyncpg
import pytest

from conftest import TENANT_A
from dealerai.config import get_settings
from dealerai.connectors import channels
from dealerai.connectors.base import ConnectorError, RateLimited, RequestRejected
from dealerai.connectors.mock import MockConnector
from dealerai.db.session import tenant_session
from dealerai.events.bus import Event
from dealerai.events.handlers import content
from dealerai.events.handlers.lifecycle import on_vehicle_sold
from dealerai.routes.content import ContentDetail, _detail
from dealerai.sales.clock import zone
from dealerai.schedule import Rules
from test_content_review import SECRET, _made_a_piece

DUBAI = zone("Asia/Dubai")

# --------------------------------------------------------------------------
# the words and the pictures — pure
# --------------------------------------------------------------------------


def _copy(locale: str, caption: str, tags: list[str]) -> dict[str, Any]:
    return {"locale": locale, "hook": None, "caption": caption, "cta": None, "hashtags": tags}


def test_a_caption_is_every_language_first_language_first() -> None:
    copies = [_copy("en", "Just in.", ["mg6", "dubai"]), _copy("ar", "وصلت.", ["mg6"])]
    assert content.caption(copies, ["ar", "en"]) == "وصلت.\n\nJust in.\n\n#mg6 #dubai"
    long = [_copy("en", "x" * 1500, []), _copy("ar", "y" * 1500, [])]
    assert content.caption(long, ["en", "ar"]) == "x" * 1500, "over the limit, the first alone"


def test_a_kind_takes_the_images_it_needs() -> None:
    assets = [
        {"aspect_ratio": "1:1", "locale": "en", "n": 1},
        {"aspect_ratio": "4:5", "locale": "ar", "n": 2},
        {"aspect_ratio": "4:5", "locale": "en", "n": 3},
        {"aspect_ratio": "9:16", "locale": "en", "n": 4},
    ]
    assert content.images(assets, "post", "en") == ("post", [assets[2]])
    assert content.images(assets, "story", "en") == ("story", [assets[3]])
    assert content.images(assets, "carousel", "en") == ("post", [assets[2]]), "one is a post"
    assert content.images(assets[:2], "story", "en") == ("story", [])


def test_a_moved_post_keeps_out_of_quiet_hours() -> None:
    rules = Rules(quiet=(time(23), time(7)))
    evening = datetime(2026, 11, 9, 21, 30, tzinfo=DUBAI)
    late = datetime(2026, 11, 9, 22, 30, tzinfo=DUBAI)
    assert content.later(evening, rules, DUBAI) == datetime(2026, 11, 9, 22, 30, tzinfo=DUBAI)
    assert content.later(late, rules, DUBAI) == datetime(2026, 11, 10, 7, 0, tzinfo=DUBAI)
    assert content.backoff(2, ConnectorError("x")) == timedelta(seconds=60)
    assert content.backoff(1, RateLimited(retry_after_seconds=300)) == timedelta(seconds=300)


# --------------------------------------------------------------------------
# through the worker
# --------------------------------------------------------------------------


@pytest.fixture
async def piece(
    _migrated: None, db: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[uuid.UUID]:
    """The seeded MG6's approved piece, scheduled a second ago, and the dealer's
    Instagram and Facebook on the mock."""
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)
    channels.local_social.clear()
    made = (await _made_a_piece("scheduled"))["piece"]
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            "update content_items set scheduled_at = now() - interval '1 second' where id = $1",
            made,
        )
        await conn.execute(
            """insert into channels (tenant_id, platform, external_id, credentials)
               values ($1, 'instagram', 't-ig', '{"provider":"mock"}'),
                      ($1, 'facebook', 't-fb', '{"provider":"mock"}')""",
            TENANT_A,
        )
    finally:
        await conn.close()
    yield made
    channels.local_social.clear()


def _event(event_type: str, payload: dict[str, Any]) -> Event:
    return Event(0, TENANT_A, event_type, payload, 1, None)


async def _due(
    su: asyncpg.Connection, event_type: str = "content.publish_due"
) -> list[dict[str, Any]]:
    rows = await su.fetch(
        "select payload, run_after from events where event_type = $1 order by id", event_type
    )
    return [{"payload": json.loads(r["payload"]), "run_after": r["run_after"]} for r in rows]


async def _publications(su: asyncpg.Connection, piece: uuid.UUID) -> dict[str, asyncpg.Record]:
    rows = await su.fetch(
        """select ch.platform, p.* from publications p join channels ch on ch.id = p.channel_id
            where p.content_item_id = $1""",
        piece,
    )
    return {row["platform"]: row for row in rows}


async def _item(su: asyncpg.Connection, piece: uuid.UUID) -> asyncpg.Record:
    return await su.fetchrow(
        "select status, scheduled_at, published_at, rejection_reason from content_items "
        "where id = $1",
        piece,
    )


EXTERNAL = {"instagram": "t-ig", "facebook": "t-fb"}


def _mock(platform: str, **kw: Any) -> MockConnector:
    """The channel's own mock, set up before the first publish reaches it."""
    connector = MockConnector(platform=platform, **kw)
    channels.local_social[f"{platform}:{EXTERNAL[platform]}"] = connector
    return connector


async def test_a_due_piece_goes_out_on_every_account_and_its_numbers_are_booked(
    piece: uuid.UUID, su: asyncpg.Connection
) -> None:
    """The acceptance's first line: the pass that runs every few seconds finds
    the piece, and the worker publishes it to both accounts."""
    assert content.DUE_EVERY_SECONDS <= 30, "a minute from the slot, with a poll to spare"
    later_piece = await su.fetchval(
        """insert into content_items (tenant_id, vehicle_id, kind, status, scheduled_at)
           select tenant_id, vehicle_id, 'story', 'scheduled', now() + interval '1 minute'
             from content_items where id = $1 returning id""",
        piece,
    )
    assert await content.book_due() == 1
    assert await content.book_due() == 1, "booked once, however often it looks"
    [booked] = await _due(su)
    assert booked["payload"]["content_item_id"] == str(piece) != str(later_piece)

    await content.on_publish_due(_event("content.publish_due", booked["payload"]))

    item = await _item(su, piece)
    assert item["status"] == "published" and item["published_at"] is not None
    went = await _publications(su, piece)
    assert sorted(went) == ["facebook", "instagram"]
    assert all(p["status"] == "published" and p["permalink"] for p in went.values())
    ig = channels.local_social["instagram:t-ig"].published
    [(key, _)] = ig.items()
    assert key == f"publication:{went['instagram']['id']}", "the row is the idempotency key"

    [published] = await _due(su, "content.published")
    await content.on_published(_event("content.published", published["payload"]))
    metrics = await _due(su, "content.metrics_due")
    assert len(metrics) == 8, "four windows on each account"
    first = next(m for m in metrics if m["payload"]["window"] == "1h")
    await content.on_metrics_due(_event("content.metrics_due", first["payload"]))
    await content.on_metrics_due(_event("content.metrics_due", first["payload"]))
    assert await su.fetchval("select count(*) from content_metrics") == 1, "read once"


async def test_instagram_goes_out_and_facebook_refuses(
    piece: uuid.UUID, su: asyncpg.Connection
) -> None:
    """The acceptance's second line, read back the way a person reads it."""
    _mock("facebook", fail_next=RequestRejected("the page may not post yet", code="368"))
    await content.book_due()
    [booked] = await _due(su)
    await content.on_publish_due(_event("content.publish_due", booked["payload"]))

    assert (await _item(su, piece))["status"] == "published"
    went = await _publications(su, piece)
    assert (went["instagram"]["status"], went["facebook"]["status"]) == ("published", "failed")
    assert went["facebook"]["error"] == "facebook: the page may not post yet"
    assert await _due(su, "content.publish_due") == [booked], "a refusal is not tried again"
    told = await su.fetchval(
        "select title from notifications where kind = 'publish_failed' and entity ->> 'id' = $1",
        str(piece),
    )
    assert told == "Published on Instagram; Facebook refused it"

    async with tenant_session(TENANT_A) as conn:
        shown = ContentDetail.model_validate(await _detail(conn, TENANT_A, piece))
    by = {p.platform: p.model_dump() for p in shown.publications}
    assert by["facebook"]["error"] == "facebook: the page may not post yet"
    assert by["instagram"]["permalink"].startswith("https://instagram.test/p/")


async def test_a_failure_that_may_pass_is_tried_again_and_posts_once(
    piece: uuid.UUID, su: asyncpg.Connection
) -> None:
    ig = _mock("instagram", fail_next=ConnectorError("the platform timed out"))
    await content.book_due()
    [booked] = await _due(su)
    await content.on_publish_due(_event("content.publish_due", booked["payload"]))

    assert (await _item(su, piece))["status"] == "publishing"
    went = await _publications(su, piece)
    assert (went["instagram"]["status"], went["instagram"]["attempts"]) == ("pending", 1)
    [_, retry] = await _due(su)
    assert retry["run_after"] > datetime.now(UTC), "tried again later, not at once"

    await content.on_publish_due(_event("content.publish_due", retry["payload"]))
    went = await _publications(su, piece)
    assert (went["instagram"]["status"], went["instagram"]["attempts"]) == ("published", 2)
    assert went["facebook"]["attempts"] == 1, "what went out is not sent again"
    assert len(ig.published) == 1
    assert (await _item(su, piece))["status"] == "published"


async def test_three_failures_and_nothing_went_out_is_a_failed_piece(
    piece: uuid.UUID, su: asyncpg.Connection
) -> None:
    ig, fb = _mock("instagram"), _mock("facebook")
    await content.book_due()
    payload = (await _due(su))[0]["payload"]
    for _ in range(content.ATTEMPTS):
        ig.fail_next, fb.fail_next = ConnectorError("down"), ConnectorError("down")
        await content.on_publish_due(_event("content.publish_due", payload))
        payload = {"content_item_id": str(piece)}
    item = await _item(su, piece)
    assert item["status"] == "failed"
    assert item["rejection_reason"] == "facebook: down; instagram: down"
    assert {p["status"] for p in (await _publications(su, piece)).values()} == {"failed"}


async def test_a_sold_car_cancels_its_scheduled_pieces(
    piece: uuid.UUID, su: asyncpg.Connection
) -> None:
    """The acceptance's third line — the sale's own event — and the last look
    before sending, for a car that sold without one."""
    vehicle = await su.fetchval("select vehicle_id from content_items where id = $1", piece)
    await on_vehicle_sold(_event("vehicle.sold", {"vehicle_id": str(vehicle), "status": "sold"}))
    assert (await _item(su, piece))["status"] == "archived"
    assert await content.book_due() == 0

    await su.execute(
        "update content_items set status = 'scheduled', rejection_reason = null where id = $1",
        piece,
    )
    await su.execute("update vehicles set status = 'reserved' where id = $1", vehicle)
    await content.book_due()
    [booked] = await _due(su)
    await content.on_publish_due(_event("content.publish_due", booked["payload"]))
    item = await _item(su, piece)
    assert (item["status"], item["rejection_reason"]) == ("archived", "the car is reserved")
    assert await _publications(su, piece) == {}
    assert channels.local_social == {}, "no account was reached"


async def test_an_image_at_an_old_price_does_not_go_out(
    piece: uuid.UUID, su: asyncpg.Connection
) -> None:
    """The words name no price; the picture does, and the car's has moved."""
    await su.execute(
        """update content_assets set render_meta = render_meta || '{"price_minor": 6600000}'
            where content_item_id = $1""",
        piece,
    )
    await su.execute(
        "update content_copy set caption = 'The MG6 is here.' where content_item_id = $1", piece
    )
    await su.execute(
        """update vehicles set price_minor = 6400000
            where id = (select vehicle_id from content_items where id = $1)""",
        piece,
    )
    await content.book_due()
    [booked] = await _due(su)
    await content.on_publish_due(_event("content.publish_due", booked["payload"]))
    item = await _item(su, piece)
    assert item["status"] == "rejected"
    assert item["rejection_reason"].startswith("the price changed to AED 64,000")
    assert await _publications(su, piece) == {}


async def test_with_no_account_it_waits_an_hour_and_says_so(
    piece: uuid.UUID, su: asyncpg.Connection
) -> None:
    await su.execute("update channels set status = 'expired' where tenant_id = $1", TENANT_A)
    before = (await _item(su, piece))["scheduled_at"]
    await content.book_due()
    [booked] = await _due(su)
    await content.on_publish_due(_event("content.publish_due", booked["payload"]))
    item = await _item(su, piece)
    assert item["status"] == "scheduled"
    assert item["scheduled_at"] - before > timedelta(minutes=59)
    assert await su.fetchval(
        "select count(*) from notifications where kind = 'channel_disconnected'"
    )
    assert await content.book_due() == 0, "not due again until its new slot"


async def test_a_piece_moved_after_it_was_booked_waits_for_its_new_slot(
    piece: uuid.UUID, su: asyncpg.Connection
) -> None:
    await content.book_due()
    [booked] = await _due(su)
    await su.execute(
        "update content_items set scheduled_at = now() + interval '1 day' where id = $1", piece
    )
    await content.on_publish_due(_event("content.publish_due", booked["payload"]))
    assert (await _item(su, piece))["status"] == "scheduled"
    assert await _publications(su, piece) == {}
