"""Object storage for vehicle media and rendered creative.

Supabase Storage over HTTP. Paths are `{tenant_id}/{kind}/{yyyy}/{mm}/{ulid}.{ext}`
so a tenant's objects are contiguous and a bucket listing cannot accidentally
walk across tenants.
"""

from __future__ import annotations

import httpx

from ..config import get_settings
from ..core.errors import AppError


class StorageUnavailable(AppError):
    status = 503
    slug = "storage-unavailable"
    title = "Object storage is not configured"


class ObjectNotFound(AppError):
    status = 404
    slug = "object-not-found"
    title = "No such stored object"


BUCKET = "media"


def _base_url() -> str:
    url = get_settings().supabase_url
    if not url:
        raise StorageUnavailable("SUPABASE_URL is not set")
    return url.rstrip("/")


async def download(storage_path: str) -> bytes:
    """Fetch an object's bytes.

    Uses the anon key with RLS-backed storage policies rather than the service
    role — the same rule as the database. A storage path is not a capability.
    """
    settings = get_settings()
    if not settings.supabase_anon_key:
        raise StorageUnavailable("SUPABASE_ANON_KEY is not set")

    url = f"{_base_url()}/storage/v1/object/{BUCKET}/{storage_path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            url,
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {settings.supabase_anon_key}",
            },
        )
    if response.status_code == 404:
        raise ObjectNotFound(storage_path)
    response.raise_for_status()
    return response.content
