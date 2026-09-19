"""Resolve a WhatsApp sender to one customer inside the caller's transaction."""

from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

log = structlog.get_logger()

_CALLING_CODES = {
    "971": "AE",
    "213": "DZ",
    "212": "MA",
    "20": "EG",
}


def _phone(wa_id: str | None) -> str | None:
    """A wa_id is a phone number without the plus. Anything else is not one.

    Ignored rather than raised: Meta omits this field for customers with a
    username, and a value we cannot parse must not cost us the message — the
    BSUID identifies the customer on its own.
    """
    if not wa_id:
        return None
    digits = wa_id.strip().removeprefix("+")
    if not digits.isdigit() or not 7 <= len(digits) <= 15 or digits.startswith("0"):
        # Never log the value itself: an unparsed wa_id is still someone's number.
        log.warning("whatsapp_wa_id_not_e164", length=len(digits))
        return None
    return f"+{digits}"


def _country(bsuid: str | None, phone: str | None) -> str | None:
    if bsuid and "." in bsuid:
        prefix = bsuid.split(".", 1)[0].upper()
        if len(prefix) == 2 and prefix.isalpha():
            return prefix
    digits = (phone or "").removeprefix("+")
    return next(
        (country for code, country in _CALLING_CODES.items() if digits.startswith(code)), None
    )


async def resolve_whatsapp_identity(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    bsuid: str | None,
    wa_id: str | None,
    profile_name: str | None,
    team_id: UUID | None,
) -> UUID:
    """Find BSUID, then phone, then create; attach every identity learned.

    The caller owns the transaction. Advisory locks serialize overlapping
    first deliveries while the unique identity index remains the backstop.
    """
    bsuid = bsuid.strip() if bsuid and bsuid.strip() else None
    phone = _phone(wa_id)
    if not bsuid and not phone:
        raise ValueError("at least one WhatsApp identity is required")

    for identity in sorted(value for value in (bsuid, phone) if value):
        await conn.execute(
            "select pg_advisory_xact_lock(hashtext($1), hashtext($2))",
            str(tenant_id),
            identity,
        )

    contact_id: UUID | None = None
    if bsuid:
        contact_id = await conn.fetchval(
            """select contact_id from contact_identities
               where tenant_id = $1 and kind = 'whatsapp_user_id' and value = $2""",
            tenant_id,
            bsuid,
        )
    if contact_id is None and phone:
        contact_id = await conn.fetchval(
            """select contact_id from contact_identities
               where tenant_id = $1 and kind = 'phone' and value = $2""",
            tenant_id,
            phone,
        )
    if contact_id is None:
        contact_id = await conn.fetchval(
            """insert into contacts
                 (tenant_id, full_name, country, source, team_id)
               values ($1, $2, $3, 'whatsapp', $4) returning id""",
            tenant_id,
            profile_name or None,
            _country(bsuid, phone),
            team_id,
        )

    for kind, value in (("whatsapp_user_id", bsuid), ("phone", phone)):
        if value:
            await conn.execute(
                """insert into contact_identities
                     (tenant_id, contact_id, kind, value, is_primary, verified_at)
                   select $1, $2, $3, $4,
                          not exists (
                            select 1 from contact_identities
                            where contact_id = $2 and kind = $3 and is_primary
                          ),
                          now()
                   on conflict (tenant_id, kind, value) do nothing""",
                tenant_id,
                contact_id,
                kind,
                value,
            )

    if profile_name:
        await conn.execute(
            """update contacts set full_name = $2, last_seen_at = now()
               where id = $1 and profile_updated_at is null""",
            contact_id,
            profile_name,
        )
    else:
        await conn.execute("update contacts set last_seen_at = now() where id = $1", contact_id)
    return contact_id
