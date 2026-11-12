"""The dealership's brand: read from its own assets into a draft, and confirmed
by a person. docs/09 § T3.1.

`/brand/read` writes a draft and nothing else. `/brand/confirm` is the only
path into the columns every agent reads — the copywriter's voice, the
compositor's colours, the calls to action a post may end with — and it is a
person's request, on a person's session: Postgres refuses a confirmed profile
with nobody's name on it (0027_brand_confirmation.sql).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field, field_validator

from ..agents.content import brand_ingest
from ..core.errors import Unusable
from ..db.session import tenant_session
from ..deps import TenantContext, require_permission
from ..media import storage

log = structlog.get_logger()

router = APIRouter(prefix="/v1/brand", tags=["brand"])

Owner = Annotated[TenantContext, Depends(require_permission("settings.brand"))]

_IMAGES = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_BYTES = 10 * 1024 * 1024
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class Colours(BaseModel):
    primary: str
    secondary: str | None = None
    accent: str | None = None
    bg: str | None = None
    text: str | None = None

    @field_validator("primary", "secondary", "accent", "bg", "text")
    @classmethod
    def _hex(cls, value: str | None) -> str | None:
        if value is not None and not _HEX.match(value):
            raise ValueError("a colour is written #RRGGBB")
        return value.upper() if value else value


class Face(BaseModel):
    family: str = Field(min_length=1, max_length=60)
    weight: int | None = Field(default=None, ge=100, le=900)
    style: str | None = Field(default=None, max_length=20)


class Typography(BaseModel):
    heading: Face | None = None
    body: Face | None = None
    arabic: Face | None = None


class Tone(BaseModel):
    voice: str | None = Field(default=None, max_length=30)
    person: str | None = Field(default=None, max_length=20)
    formality: str | None = Field(default=None, max_length=20)
    emoji: Literal["none", "sparse", "frequent"] | None = None


class Cta(BaseModel):
    text: str = Field(min_length=1, max_length=90)
    locale: Literal["en", "ar", "fr"]


class HashtagRules(BaseModel):
    max: int = Field(default=8, ge=0, le=30)


class BrandConfirmation(BaseModel):
    """The brand as a person read it and accepted it — the draft, edited or not."""

    display_name: str | None = Field(default=None, max_length=120)
    colors: Colours
    typography: Typography = Field(default_factory=Typography)
    tone: Tone = Field(default_factory=Tone)
    cta_styles: list[Cta] = Field(default_factory=list, max_length=12)
    hashtag_rules: HashtagRules = Field(default_factory=HashtagRules)
    photography_style: str | None = Field(default=None, max_length=200)
    logo_asset_id: UUID | None = None


class BrandOut(BaseModel):
    confirmed: bool
    confirmed_at: datetime | None
    confirmed_by: str | None
    display_name: str | None
    colors: dict[str, Any]
    typography: dict[str, Any]
    tone: dict[str, Any]
    cta_styles: list[Any]
    hashtag_rules: dict[str, Any]
    photography_style: str | None
    logo_asset_id: UUID | None
    #: The last reading, waiting for a person. Never what agents read.
    draft: dict[str, Any] | None
    draft_at: datetime | None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


async def _brand(conn: asyncpg.Connection, tenant_id: UUID) -> dict[str, Any]:
    await conn.execute(
        """insert into brand_profiles (tenant_id, display_name)
           select id, name from tenants where id = $1
           on conflict (tenant_id) do nothing""",
        tenant_id,
    )
    row = await conn.fetchrow(
        """select b.*, p.full_name as confirmer
             from brand_profiles b left join profiles p on p.id = b.confirmed_by
            where b.tenant_id = $1""",
        tenant_id,
    )
    return {
        "confirmed": row["confirmed_at"] is not None,
        "confirmed_at": row["confirmed_at"],
        "confirmed_by": row["confirmer"],
        **{
            name: row[name]
            for name in (
                "display_name",
                "colors",
                "typography",
                "tone",
                "cta_styles",
                "hashtag_rules",
                "photography_style",
                "logo_asset_id",
                "draft",
                "draft_at",
            )
        },
    }


async def _image(upload: UploadFile) -> tuple[bytes, str]:
    mime = (upload.content_type or "").split(";")[0].strip().lower()
    if mime not in _IMAGES:
        raise Unusable(
            "a logo or a post is a JPEG, PNG or WebP image",
            ar="الشعار أو المنشور يكون صورة JPEG أو PNG أو WebP.",
        )
    data = await upload.read()
    if not data or len(data) > MAX_BYTES:
        raise Unusable(
            "each image must be under 10 MB and not empty",
            ar="كل صورة يجب ألا تكون فارغة وأن تكون أصغر من ١٠ ميجابايت.",
        )
    return data, mime


def split_captions(text: str) -> list[str]:
    """Captions pasted as they were posted: separated by a blank line or ---."""
    return [part.strip() for part in re.split(r"\n\s*(?:---+\s*)?\n", text) if part.strip()]


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------


@router.get("", response_model=BrandOut)
async def get_brand(ctx: Owner) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        return await _brand(conn, ctx.tenant_id)


@router.post("/read", response_model=BrandOut)
async def read_brand(
    ctx: Owner,
    logo: Annotated[UploadFile | None, File()] = None,
    posts: Annotated[list[UploadFile] | None, File()] = None,
    captions: Annotated[str, Form(max_length=40_000)] = "",
) -> dict[str, Any]:
    """Read the logo, past posts and past captions into a draft. Changes
    nothing any agent reads."""
    posts = posts or []
    if len(posts) > brand_ingest.MAX_POSTS:
        raise Unusable(
            f"send at most {brand_ingest.MAX_POSTS} past posts",
            ar=f"أرسل {brand_ingest.MAX_POSTS} منشورات سابقة على الأكثر.",
        )
    logo_image = await _image(logo) if logo is not None else None
    post_images = [await _image(post) for post in posts]
    texts = split_captions(captions)
    if logo_image is None and not post_images and not texts:
        raise Unusable(
            "send a logo, some past posts or some past captions",
            ar="أرسل الشعار أو منشورات سابقة أو نصوص منشورات سابقة.",
        )

    draft = await brand_ingest.read(
        tenant_id=ctx.tenant_id, logo=logo_image, posts=post_images, captions=texts
    )

    if logo_image is not None:
        data, mime = logo_image
        path = storage.object_path(ctx.tenant_id, "brand", storage.extension_for(mime))
        try:
            await storage.upload(path, data, content_type=mime)
            async with tenant_session(ctx.tenant_id) as conn:
                draft["logo_asset_id"] = str(
                    await conn.fetchval(
                        """insert into brand_assets (tenant_id, kind, storage_path, mime, meta)
                           values ($1, 'logo', $2, $3, $4) returning id""",
                        ctx.tenant_id,
                        path,
                        mime,
                        {"palette": draft["palette"]},
                    )
                )
        except Exception as exc:  # noqa: BLE001 - the reading is still worth showing
            log.warning("logo_not_stored", error=str(exc))
            draft["warnings"].append("the logo could not be kept; the reading is still usable")

    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        await _brand(conn, ctx.tenant_id)
        await conn.execute(
            "update brand_profiles set draft = $2, draft_at = now() where tenant_id = $1",
            ctx.tenant_id,
            draft,
        )
        return await _brand(conn, ctx.tenant_id)


@router.post("/confirm", response_model=BrandOut)
async def confirm_brand(body: BrandConfirmation, ctx: Owner) -> dict[str, Any]:
    """A person accepts the brand: what agents read from now on. The only way
    the profile reaches the confirmed state."""
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id) as conn, conn.transaction():
        current = await _brand(conn, ctx.tenant_id)
        if body.logo_asset_id is not None and not await conn.fetchval(
            "select 1 from brand_assets where id = $1 and kind = 'logo'", body.logo_asset_id
        ):
            raise Unusable(
                "that logo is not one of this dealership's",
                ar="هذا الشعار ليس من شعارات هذا المعرض.",
            )
        await conn.execute(
            """update brand_profiles set
                 display_name = coalesce($2, display_name),
                 colors = $3, typography = $4, tone = $5, cta_styles = $6,
                 hashtag_rules = $7, photography_style = $8,
                 logo_asset_id = coalesce($9, logo_asset_id),
                 confirmed_at = now(), confirmed_by = $10,
                 draft = null, draft_at = null
               where tenant_id = $1""",
            ctx.tenant_id,
            body.display_name,
            body.colors.model_dump(exclude_none=True),
            body.typography.model_dump(exclude_none=True),
            body.tone.model_dump(exclude_none=True),
            [cta.model_dump() for cta in body.cta_styles],
            body.hashtag_rules.model_dump(),
            body.photography_style,
            body.logo_asset_id,
            ctx.user.id,
        )
        await conn.execute(
            """insert into audit_log (tenant_id, actor_type, actor_id, action, entity_type,
                                      entity_id, before, after)
               values ($1, 'user', $2, 'brand.confirmed', 'brand_profile', $1, $3, $4)""",
            ctx.tenant_id,
            str(ctx.user.id),
            {k: current[k] for k in ("colors", "tone", "cta_styles")},
            body.model_dump(mode="json", exclude_none=True),
        )
        log.info("brand_confirmed", tenant_id=str(ctx.tenant_id))
        return await _brand(conn, ctx.tenant_id)


@router.delete("/draft", response_model=BrandOut)
async def discard_draft(ctx: Owner) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        await _brand(conn, ctx.tenant_id)
        await conn.execute(
            "update brand_profiles set draft = null, draft_at = null where tenant_id = $1",
            ctx.tenant_id,
        )
        return await _brand(conn, ctx.tenant_id)
