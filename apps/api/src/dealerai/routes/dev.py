"""Local-only sign-in: as a seeded person, or as somebody new.

Local Postgres has no Supabase Auth server, so without this nobody can see the
app as Ahmed or Sara — nor sign up, so no invitation could ever be accepted
here. It mints the token Supabase Auth would issue, through mint_test_token so
the claim shape cannot drift from what decode_supabase_jwt verifies, and puts
somebody new where Supabase would: in auth.users.

Two locks, so a misconfigured deploy fails closed twice: main.create_app mounts
this router only when ENV=local, and every handler re-checks. It is also kept
out of the OpenAPI schema, so local and CI generate identical frontend types.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import get_settings
from ..core.errors import NotFound
from ..core.security import AuthUnavailable, mint_test_token
from ..scripts.seed_sales import (
    PEOPLE,
    TENANT,
    TENANT_SLUG,
    local_person,
    person_email,
    person_id,
)

router = APIRouter(prefix="/internal/dev", tags=["dev"], include_in_schema=False)

#: Long enough for a working day of local testing.
SESSION_SECONDS = 12 * 3600


class DevPerson(BaseModel):
    email: str
    name: str
    role: str


class DevSessionIn(BaseModel):
    email: str
    name: str | None = None


class DevSession(BaseModel):
    access_token: str
    #: The seeded workspace for the seeded five; nobody's for anybody else.
    tenant_id: UUID | None
    tenant_slug: str | None


def _local_only() -> None:
    if get_settings().env != "local":
        raise NotFound("not found")


@router.get("/people", response_model=list[DevPerson])
async def list_people() -> list[DevPerson]:
    _local_only()
    return [DevPerson(email=person_email(name), name=name, role=role) for name, role, *_ in PEOPLE]


@router.post("/session", response_model=DevSession)
async def create_session(body: DevSessionIn) -> DevSession:
    _local_only()
    settings = get_settings()
    secret = settings.supabase_jwt_secret
    if not secret:
        raise AuthUnavailable("SUPABASE_JWT_SECRET is not set")
    email = body.email.strip().lower()
    seeded = {person_email(name): name for name, *_ in PEOPLE}.get(email)
    if seeded:
        token = mint_test_token(
            person_id(seeded),
            secret=secret,
            email=email,
            name=seeded,
            expires_in_seconds=SESSION_SECONDS,
        )
        return DevSession(access_token=token, tenant_id=TENANT, tenant_slug=TENANT_SLUG)

    # Somebody new: where Supabase would put them on sign-up.
    user_id = await local_person(email)
    token = mint_test_token(
        user_id,
        secret=secret,
        email=email,
        name=body.name,
        expires_in_seconds=SESSION_SECONDS,
    )
    return DevSession(access_token=token, tenant_id=None, tenant_slug=None)
