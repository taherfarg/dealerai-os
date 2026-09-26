"""Local-only sign-in as a seeded person.

Local Postgres has no Supabase Auth server, so without this nobody can see the
app as Ahmed or Sara. It mints the token Supabase Auth would issue, through
mint_test_token so the claim shape cannot drift from what decode_supabase_jwt
verifies.

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
from ..scripts.seed_sales import PEOPLE, TENANT, TENANT_SLUG, person_email, person_id

router = APIRouter(prefix="/internal/dev", tags=["dev"], include_in_schema=False)

#: Long enough for a working day of local testing.
SESSION_SECONDS = 12 * 3600


class DevPerson(BaseModel):
    email: str
    name: str
    role: str


class DevSessionIn(BaseModel):
    email: str


class DevSession(BaseModel):
    access_token: str
    tenant_id: UUID
    tenant_slug: str


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
    by_email = {person_email(name): name for name, *_ in PEOPLE}
    name = by_email.get(body.email)
    if name is None:
        raise NotFound("no seeded person with that email")
    secret = get_settings().supabase_jwt_secret
    if not secret:
        raise AuthUnavailable("SUPABASE_JWT_SECRET is not set")
    token = mint_test_token(
        person_id(name),
        secret=secret,
        email=body.email,
        expires_in_seconds=SESSION_SECONDS,
    )
    return DevSession(access_token=token, tenant_id=TENANT, tenant_slug=TENANT_SLUG)
