"""T3.7: a person reviews what the content run made.

The acceptance is the spine of this file: a user watches generation live over
SSE, edits one caption, approves, and the piece reaches `approved` — with
`edited_by_human` set on the copy row that was edited and no other.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, SALES_1, TENANT_A, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


def auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


async def _made_a_piece(status: str = "pending_approval") -> dict[str, uuid.UUID]:
    """What a content run leaves: a finished run, its task, and one piece for
    the seeded MG6 (AED 66,000) with copy in two languages and one image."""
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        vehicle = await conn.fetchval(
            "select id from vehicles where tenant_id = $1 and model = 'MG6'", TENANT_A
        )
        run = await conn.fetchval(
            """insert into agent_runs (tenant_id, trigger_type, autonomy, status, goal,
                                       finished_at)
               values ($1, 'user', 'copilot', 'completed', 'sell this stock', now())
               returning id""",
            TENANT_A,
        )
        await conn.execute(
            """insert into agent_tasks (tenant_id, run_id, task_key, agent, status)
               values ($1, $2, 'plan', 'content_strategist', 'completed')""",
            TENANT_A,
            run,
        )
        piece = await conn.fetchval(
            """insert into content_items (tenant_id, vehicle_id, run_id, kind, concept, status)
               values ($1, $2, $3, 'post', 'just_arrived', $4) returning id""",
            TENANT_A,
            vehicle,
            run,
            status,
        )
        await conn.execute(
            """insert into content_copy (tenant_id, content_item_id, locale, hook, caption, cta,
                                         hashtags)
               values ($1, $2, 'en', 'Just in', 'The MG6 is here. AED 66,000.', 'Book a viewing',
                       '{mg6,dubai}'),
                      ($1, $2, 'ar', 'وصلت للتو', 'وصلت MG6 الآن.', 'احجز معاينة', '{}')""",
            TENANT_A,
            piece,
        )
        await conn.execute(
            """insert into content_assets (tenant_id, content_item_id, aspect_ratio, storage_path,
                                           mime, width, height, render_meta)
               values ($1, $2, '4:5', $3, 'image/png', 1080, 1350, '{"locale": "en"}')""",
            TENANT_A,
            piece,
            f"{TENANT_A}/content/{piece}/en-4x5.png",
        )
        return {"run": run, "piece": piece}
    finally:
        await conn.close()


@pytest.fixture
def made(_migrated: None, monkeypatch: pytest.MonkeyPatch) -> dict[str, uuid.UUID]:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)
    return asyncio.run(_made_a_piece())


@pytest.fixture
def client(made: dict[str, uuid.UUID]) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _frames(body: str) -> list[tuple[str, str]]:
    out = []
    for block in body.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], lines.get("data", "")))
    return out


def test_watch_edit_approve(client: TestClient, made: dict[str, uuid.UUID]) -> None:
    """The acceptance, end to end through the API."""
    run, piece = made["run"], made["piece"]

    with client.stream("GET", f"/v1/runs/{run}/stream", headers=auth(MANAGER)) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = _frames(response.read().decode())
    events = [event for event, _ in frames]
    assert events[:2] == ["task.updated", "content.updated"]
    assert events[-1] == "run.completed", "a finished run ends its stream"
    assert str(piece) in dict(frames)["content.updated"]

    edited = client.patch(
        f"/v1/content/{piece}/copy/en",
        json={"caption": "The MG6 has landed: AED 66,000, ready to drive."},
        headers=auth(MANAGER),
    )
    assert edited.status_code == 200, edited.text
    copies = {c["locale"]: c for c in edited.json()["copies"]}
    assert copies["en"]["caption"] == "The MG6 has landed: AED 66,000, ready to drive."
    assert copies["en"]["hook"] == "Just in", "what was not sent is kept"
    assert (copies["en"]["edited_by_human"], copies["ar"]["edited_by_human"]) == (True, False)

    approved = client.post(f"/v1/content/{piece}/approve", headers=auth(MANAGER))
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_at"] is not None
    assert client.post(f"/v1/content/{piece}/approve", headers=auth(MANAGER)).status_code == 409


def test_a_piece_is_shown_with_its_words_and_its_images(
    client: TestClient, made: dict[str, uuid.UUID]
) -> None:
    piece = client.get(f"/v1/content/{made['piece']}", headers=auth(SALES_1)).json()
    assert piece["vehicle"] == "MG MG6"
    assert [c["locale"] for c in piece["copies"]] == ["ar", "en"]
    [image] = piece["images"]
    assert (image["aspect_ratio"], image["locale"]) == ("4:5", "en")
    assert "/v1/media/" in image["url"], "a signed link, never the storage path"
    listed = next(
        item
        for item in client.get("/v1/content", headers=auth(SALES_1)).json()
        if item["id"] == str(made["piece"])
    )
    assert "/v1/media/" in listed["thumbnail_url"], "the grid shows the first image"


def test_a_person_cannot_type_a_price_the_car_does_not_have(
    client: TestClient, made: dict[str, uuid.UUID]
) -> None:
    refused = client.patch(
        f"/v1/content/{made['piece']}/copy/en",
        json={"caption": "Yours for AED 59,000 this week only."},
        headers=auth(MANAGER),
    )
    assert refused.status_code == 422
    assert "59,000" in refused.text
    after = client.get(f"/v1/content/{made['piece']}", headers=auth(MANAGER)).json()
    en = next(c for c in after["copies"] if c["locale"] == "en")
    assert en["edited_by_human"] is False, "a refused edit changes nothing"


def test_who_may_review_and_what_a_rejection_needs(
    client: TestClient, made: dict[str, uuid.UUID]
) -> None:
    piece = made["piece"]
    for call in (
        lambda h: client.post(f"/v1/content/{piece}/approve", headers=h),
        lambda h: client.post(f"/v1/content/{piece}/reject", json={"reason": "no"}, headers=h),
        lambda h: client.patch(f"/v1/content/{piece}/copy/en", json={"cta": "Hi"}, headers=h),
    ):
        assert call(auth(SALES_1)).status_code == 403
    no_reason = client.post(
        f"/v1/content/{piece}/reject", json={"reason": ""}, headers=auth(MANAGER)
    )
    assert no_reason.status_code == 400, "a rejection says why"

    client.post(f"/v1/content/{piece}/approve", headers=auth(MANAGER))
    taken_back = client.post(
        f"/v1/content/{piece}/reject",
        json={"reason": "The bumper photo is from another car"},
        headers=auth(MANAGER),
    )
    assert taken_back.status_code == 200, taken_back.text
    body: dict[str, Any] = taken_back.json()
    assert (body["status"], body["approved_at"]) == ("rejected", None)
    assert body["rejection_reason"] == "The bumper photo is from another car"


def test_what_has_gone_out_cannot_be_edited(client: TestClient, made: dict[str, uuid.UUID]) -> None:
    asyncio.run(_set_status(made["piece"], "published"))
    refused = client.patch(
        f"/v1/content/{made['piece']}/copy/en", json={"cta": "Call us"}, headers=auth(MANAGER)
    )
    assert refused.status_code == 409


def test_words_printed_on_the_images_are_not_edited_under_them(
    client: TestClient, made: dict[str, uuid.UUID]
) -> None:
    """The hero template prints the call to action on every image. Changing it
    would approve a picture that says the old words — so it is refused, and the
    piece says which fields are on its images. The caption is not on a hero."""
    piece = made["piece"]
    asyncio.run(_set_brief(piece, {"template_key": "hero"}))
    shown = client.get(f"/v1/content/{piece}", headers=auth(MANAGER)).json()
    assert shown["in_image"] == ["cta"]

    refused = client.patch(
        f"/v1/content/{piece}/copy/en", json={"cta": "Call us today"}, headers=auth(MANAGER)
    )
    assert refused.status_code == 409
    assert "reject it to have it made again" in refused.text
    unchanged = client.patch(
        f"/v1/content/{piece}/copy/en",
        json={"cta": "Book a viewing", "caption": "The MG6 is in. AED 66,000."},
        headers=auth(MANAGER),
    )
    assert unchanged.status_code == 200, "sending the printed words as they are is no change"


async def _set_brief(piece: uuid.UUID, brief: dict[str, str]) -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            "update content_items set brief = $2::jsonb where id = $1", piece, json.dumps(brief)
        )
    finally:
        await conn.close()


async def _set_status(piece: uuid.UUID, status: str) -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute("update content_items set status = $2 where id = $1", piece, status)
    finally:
        await conn.close()
