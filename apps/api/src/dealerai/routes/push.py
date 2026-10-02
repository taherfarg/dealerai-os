"""A person's devices, for Web Push (docs/sales/06-api-contract.md § 7).

Everybody may subscribe their own device: there is no permission to hold,
because the rows are the caller's own (migration 0014) and a push carries only
what their bell already shows them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, status
from pydantic import BaseModel, Field, field_validator

from ..config import get_settings
from ..core.errors import AppError, NotFound, Unusable
from ..db.session import tenant_session
from ..deps import Ctx
from ..notifications import push

router = APIRouter(prefix="/v1", tags=["push"])


class PushUnavailable(AppError):
    status = 503
    slug = "push-unavailable"
    title = "Push is not configured"


class PushKey(BaseModel):
    public_key: str


def _decodes_to(value: str, length: int) -> bytes:
    try:
        raw = push.unb64(value)
    except ValueError as exc:
        raise ValueError("not base64url") from exc
    if len(raw) != length:
        raise ValueError(f"not {length} bytes")
    return raw


class PushSubscriptionIn(BaseModel):
    """What the browser's PushSubscription holds."""

    endpoint: str = Field(max_length=2048)
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=64)
    user_agent: str | None = Field(default=None, max_length=512)

    @field_validator("p256dh")
    @classmethod
    def _a_p256_point(cls, value: str) -> str:
        # Refused here rather than when the worker comes to encrypt for it: a
        # key that is no point on the curve would fail every push, forever.
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _decodes_to(value, 65))
        return value

    @field_validator("auth")
    @classmethod
    def _a_secret(cls, value: str) -> str:
        _decodes_to(value, 16)
        return value


class PushDevice(BaseModel):
    """A device as its owner sees it — never the address or the keys."""

    id: UUID
    user_agent: str | None
    created_at: datetime
    last_success_at: datetime | None


class PushTest(BaseModel):
    sent: int
    failed: int


_DEVICE = "id, user_agent, created_at, last_success_at"


def _key() -> str:
    key = get_settings().vapid_private_key
    if not key:
        raise PushUnavailable("VAPID_PRIVATE_KEY is not set")
    return key


@router.get("/push/key", response_model=PushKey)
async def push_key(ctx: Ctx) -> PushKey:
    """The public half: what a browser subscribes with."""
    return PushKey(public_key=push.public_key(_key()))


@router.get("/push-subscriptions", response_model=list[PushDevice])
async def my_devices(ctx: Ctx) -> list[dict[str, Any]]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(
            f"select {_DEVICE} from push_subscriptions order by created_at desc"  # noqa: S608
        )
    return [dict(row) for row in rows]


@router.post("/push-subscriptions", response_model=PushDevice, status_code=status.HTTP_201_CREATED)
async def subscribe(body: PushSubscriptionIn, ctx: Ctx) -> dict[str, Any]:
    """This device, for this person — whoever had it before (migration 0014)."""
    _key()
    if not push.is_push_service(body.endpoint):
        raise Unusable("that address is not a push service this server sends to")
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        device_id = await conn.fetchval(
            "select app.remember_push_subscription($1, $2, $3, $4, $5, $6)",
            ctx.tenant_id,
            ctx.user.id,
            body.endpoint,
            body.p256dh,
            body.auth,
            body.user_agent,
        )
        row = await conn.fetchrow(
            f"select {_DEVICE} from push_subscriptions where id = $1",  # noqa: S608
            device_id,
        )
    return dict(row)


@router.delete("/push-subscriptions/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(device_id: UUID, ctx: Ctx) -> None:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        gone = await conn.fetchval(
            "delete from push_subscriptions where id = $1 returning id", device_id
        )
    if gone is None:
        raise NotFound("no such device")


@router.post("/push-subscriptions/test", response_model=PushTest)
async def test_push(ctx: Ctx) -> PushTest:
    """A push to the caller's own devices, now — how somebody finds out whether
    their phone will tell them, before a customer is what finds out."""
    settings = get_settings()
    key = _key()
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        devices = await conn.fetch("select id, endpoint, p256dh, auth from push_subscriptions")
        slug = await conn.fetchval("select slug from tenants where id = $1", ctx.tenant_id)
    answers = await push.deliver(
        devices,
        push.message(
            "DealerAI",
            "Notifications are on for this device.",
            href=f"/{slug}/settings/notifications",
            tag="test",
        ),
        private=key,
        subject=settings.vapid_subject,
    )
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        await push.record(conn, answers)
    sent = sum(1 for answer in answers.values() if push.delivered(answer))
    return PushTest(sent=sent, failed=len(answers) - sent)
