"""Customers: the list, the record, its timeline, and what a person may change."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..core.errors import AlreadyMerged, NotFound, Unusable
from ..db.queries.crm import (
    IDENTITIES,
    MERGED_INTO,
    ONE_CUSTOMER,
    OPEN_LEADS,
    OPEN_TASK_COUNT,
    TIMELINE,
    list_sql,
)
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission
from ..events.bus import emit
from ..sales import profile as profile_fields
from .inbox import UserRef
from .leads import LeadOut, lead_out

router = APIRouter(prefix="/v1/customers", tags=["customers"])

#: At most this many tags on one customer, each at most this long. A tag list
#: nobody can read is a tag list nobody filters by.
_MAX_TAGS = 20
_MAX_TAG = 40


class Identity(BaseModel):
    id: UUID
    kind: str
    value: str
    is_primary: bool


class CustomerSummary(BaseModel):
    id: UUID
    name: str | None
    phone: str | None
    country: str | None
    language: str | None
    tags: list[str]
    owner: UserRef | None
    band: Literal["hot", "warm", "cold"] | None
    opted_out: bool
    last_seen_at: datetime


class CustomerDetail(CustomerSummary):
    identities: list[Identity]
    #: `{field: {value, source, evidence_message_id, updated_at}}` — see sales/profile.py.
    profile: dict[str, Any]
    profile_updated_at: datetime | None
    leads: list[LeadOut]
    open_tasks: int


class CustomerPage(BaseModel):
    data: list[CustomerSummary]
    next_cursor: str | None


class TimelineEntry(BaseModel):
    kind: Literal["message", "activity"]
    id: str
    at: datetime
    data: dict[str, Any]


class TimelinePage(BaseModel):
    data: list[TimelineEntry]
    next_offset: int | None


class CustomerPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    tags: list[str] | None = None
    #: Only the fields in sales/profile.py FIELDS; anything else is a 422.
    profile: dict[str, Any] | None = None


def _money(minor: int | None, currency: str | None) -> dict[str, Any] | None:
    return None if minor is None else {"amount_minor": minor, "currency": currency or "AED"}


def _owner(user_id: UUID | None, name: str | None) -> dict[str, Any] | None:
    return None if user_id is None else {"id": user_id, "name": name}


def summary(row: Mapping[str, Any]) -> dict[str, Any]:
    consent = dict(row["consent"] or {})
    return {
        "id": row["id"],
        "name": row["full_name"],
        "phone": row["phone"],
        "country": row["country"],
        "language": row["language"],
        "tags": list(row["tags"] or []),
        "owner": _owner(row["owner_id"], row["owner_name"]),
        "band": row["band"],
        "opted_out": bool(consent.get("opted_out_at")),
        "last_seen_at": row["last_seen_at"],
    }


def encode_cursor(row: Mapping[str, Any]) -> str:
    """Two sort keys, base64'd so nobody is tempted to build one by hand."""
    raw = f"{row['last_seen_at'].isoformat()}|{row['id']}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        seen, contact_id = base64.urlsafe_b64decode(cursor).decode().split("|")
        return datetime.fromisoformat(seen), UUID(contact_id)
    except (ValueError, binascii.Error) as exc:
        raise Unusable("that cursor is not one of ours") from exc


async def _row_or_404(conn: Any, tenant_id: UUID, customer_id: UUID) -> dict[str, Any]:
    """The customer, or 404 — which is also the answer for another tenant's id
    and for a colleague's customer we are not allowed to see.

    Except when they were merged away: then the answer is where they went, so a
    link somebody saved last week explains itself instead of looking broken.
    """
    row = await conn.fetchrow(ONE_CUSTOMER, customer_id)
    if row is not None:
        return dict(row)
    keep_id = await conn.fetchval(MERGED_INTO, tenant_id, customer_id)
    if keep_id:
        raise AlreadyMerged(
            "This customer was merged into another record.",
            # The renderer passes `errors` through untouched, which is how the
            # browser learns where to redirect without parsing a sentence.
            errors=[{"keep_id": str(keep_id)}],
        )
    raise NotFound("no such customer")


async def _detail(conn: Any, tenant_id: UUID, customer_id: UUID) -> dict[str, Any]:
    row = await _row_or_404(conn, tenant_id, customer_id)
    identities = await conn.fetch(IDENTITIES, customer_id)
    leads = await conn.fetch(OPEN_LEADS, customer_id, False)
    open_tasks = await conn.fetchval(OPEN_TASK_COUNT, customer_id)
    return {
        **summary(row),
        "identities": [dict(identity) for identity in identities],
        "profile": dict(row["profile"] or {}),
        "profile_updated_at": row["profile_updated_at"],
        "leads": [lead_out(lead) for lead in leads],
        "open_tasks": open_tasks or 0,
    }


@router.get("", response_model=CustomerPage)
async def list_customers(
    ctx: Ctx,
    q: str = "",
    owner_id: UUID | None = None,
    band: Annotated[Literal["hot", "warm", "cold"] | None, Query()] = None,
    country: str = "",
    tag: str = "",
    cursor: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    keys = decode_cursor(cursor) if cursor else None
    size = min(limit, 100)
    arguments: list[Any] = [q or None, owner_id, country.upper() or None, tag or None]
    if keys is not None:
        arguments.extend(keys)
    # One more than asked, to know whether there is another page.
    arguments.append(size + 1)

    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(list_sql(with_cursor=keys is not None), *arguments)

    page, has_more = rows[:size], len(rows) > size
    # The band filter runs over the page rather than in the where clause: it is
    # one of five filters and the only one needing a join per row. The cursor
    # still comes from where the scan stopped, so filtering cannot skip anybody.
    # ponytail: move it into the query if band becomes the common filter.
    visible = [row for row in page if band is None or row["band"] == band]
    return {
        "data": [summary(row) for row in visible],
        "next_cursor": encode_cursor(page[-1]) if has_more and page else None,
    }


@router.get("/{customer_id}", response_model=CustomerDetail)
async def get_customer(ctx: Ctx, customer_id: UUID) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        return await _detail(conn, ctx.tenant_id, customer_id)


@router.get("/{customer_id}/timeline", response_model=TimelinePage)
async def customer_timeline(
    ctx: Ctx, customer_id: UUID, offset: int = 0, limit: int = 50
) -> dict[str, Any]:
    """Every channel and every lead move, merged, newest first."""
    size = min(limit, 200)
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        await _row_or_404(conn, ctx.tenant_id, customer_id)  # 404 before anybody's history
        rows = await conn.fetch(TIMELINE, customer_id, size + 1, max(offset, 0))
    page, has_more = rows[:size], len(rows) > size
    return {
        "data": [
            {"kind": row["kind"], "id": row["id"], "at": row["at"], "data": dict(row["data"])}
            for row in page
        ],
        "next_offset": offset + size if has_more else None,
    }


@router.patch("/{customer_id}", response_model=CustomerDetail)
async def edit_customer(ctx: Ctx, customer_id: UUID, body: CustomerPatch) -> dict[str, Any]:
    """Anything typed here is a person's answer, stamped `human` — which is what
    stops the next AI run overwriting it."""
    async with (
        tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn,
        conn.transaction(),
    ):
        row = await _row_or_404(conn, ctx.tenant_id, customer_id)
        if body.name is not None:
            await conn.execute(
                "update contacts set full_name = $2 where id = $1",
                customer_id,
                body.name.strip() or None,
            )
        if body.tags is not None:
            tags = list(dict.fromkeys(tag.strip()[:_MAX_TAG] for tag in body.tags if tag.strip()))
            await conn.execute(
                "update contacts set tags = $2 where id = $1", customer_id, tags[:_MAX_TAGS]
            )
        if body.profile is not None:
            updated = profile_fields.apply(
                dict(row["profile"] or {}),
                body.profile,
                source="human",
                now=datetime.now(UTC),
            )
            await conn.execute(
                """update contacts set profile = $2::jsonb, profile_updated_at = now()
                    where id = $1""",
                customer_id,
                updated,
            )
        return await _detail(conn, ctx.tenant_id, customer_id)


class ReassignIn(BaseModel):
    owner_id: UUID


class MergeIn(BaseModel):
    keep_id: UUID
    merge_id: UUID


@router.post("/merge", response_model=CustomerDetail)
async def merge_customers(
    body: MergeIn,
    ctx: Annotated[TenantContext, Depends(require_permission("contacts.merge"))],
) -> dict[str, Any]:
    """Two records, one customer. Not undoable — the audit row is what a repair
    would start from, and the old id keeps answering with where it went."""
    async with (
        tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn,
        conn.transaction(),
    ):
        await _row_or_404(conn, ctx.tenant_id, body.keep_id)
        await _row_or_404(conn, ctx.tenant_id, body.merge_id)
        await conn.execute(
            "select app.merge_contacts($1, $2, $3)", body.keep_id, body.merge_id, ctx.user.id
        )
        return await _detail(conn, ctx.tenant_id, body.keep_id)


@router.post("/{customer_id}/reassign", response_model=CustomerDetail)
async def reassign_customer(
    customer_id: UUID,
    body: ReassignIn,
    ctx: Annotated[TenantContext, Depends(require_permission("contacts.reassign"))],
) -> dict[str, Any]:
    """The customer, their open conversations, their open leads and their open
    tasks, in one transaction — and a line in every thread that moved."""
    async with (
        tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn,
        conn.transaction(),
    ):
        await _row_or_404(conn, ctx.tenant_id, customer_id)
        member = await conn.fetchval("select app.member_role($1, $2)", ctx.tenant_id, body.owner_id)
        if member is None:
            raise NotFound("no such colleague in this workspace")
        await conn.execute(
            "select app.reassign_contact($1, $2, $3)", customer_id, body.owner_id, ctx.user.id
        )
        await emit(
            conn,
            "contact.reassigned",
            {
                "contact_id": str(customer_id),
                "owner_id": str(body.owner_id),
                "actor_id": str(ctx.user.id),
            },
            tenant_id=ctx.tenant_id,
            priority=8,
        )
        return await _detail(conn, ctx.tenant_id, customer_id)
