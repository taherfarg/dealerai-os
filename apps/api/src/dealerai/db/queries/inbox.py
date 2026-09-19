"""The inbox's SQL, in one place.

Visibility is absent on purpose: the policies in 0006 already decided which rows
exist for this session, so a view here is a filter over what the caller can see,
never a claim about what they may see.
"""

from __future__ import annotations

from typing import Literal

View = Literal["mine", "unassigned", "team", "all"]

#: Which views a scope may open. `team` and `all` belong to a manager and an
#: owner; a salesperson asking for them gets 403 rather than an empty list,
#: because an empty list reads as "no work today".
VIEWS_BY_SCOPE: dict[str, tuple[View, ...]] = {
    "own": ("mine", "unassigned"),
    "team": ("mine", "unassigned", "team"),
    "all": ("mine", "unassigned", "team", "all"),
}

VIEW_SQL: dict[View, str] = {
    "mine": "cv.assigned_to = $1",
    "unassigned": "cv.assigned_to is null",
    "team": "cv.team_id = any (coalesce((select app.my_team_ids()), '{}'))",
    "all": "true",
}

#: Waiting first, longest first, then the liveliest. Ties break on id so a page
#: boundary can never show the same row twice.
_ORDER = """
order by coalesce(cv.waiting_since, 'infinity'::timestamptz) asc,
         coalesce(cv.last_message_at, '-infinity'::timestamptz) desc,
         cv.id asc
"""

#: Mixed directions, so the keyset is written out rather than a row comparison.
_AFTER = """
and (coalesce(cv.waiting_since, 'infinity'::timestamptz) > $5
     or (coalesce(cv.waiting_since, 'infinity'::timestamptz) = $5
         and (coalesce(cv.last_message_at, '-infinity'::timestamptz) < $6
              or (coalesce(cv.last_message_at, '-infinity'::timestamptz) = $6 and cv.id > $7))))
"""

_SEARCH = """
and ($3 = ''
     or ct.full_name ilike '%' || $3 || '%'
     or exists (select 1 from contact_identities i
                 where i.contact_id = ct.id and i.value ilike '%' || $3 || '%')
     or exists (select 1 from messages m
                 where m.conversation_id = cv.id
                   and to_tsvector('simple', coalesce(m.body, '') || ' ' ||
                                   coalesce(m.transcript->>'text', ''))
                       @@ plainto_tsquery('simple', $3)))
"""

#: One channel only when the tenant has more than one (docs/sales/08-screens.md § 2);
#: an empty string means every channel.
_CHANNEL = "and ($4 = '' or cv.channel_id = $4::uuid)"

SUMMARY = """
select cv.id, cv.status, cv.last_message_at, cv.waiting_since, cv.sla_due_at,
       cv.wa_window_expires_at, cv.assigned_to, cv.team_id, cv.summary,
       ct.id as contact_id, ct.full_name, ct.country, ct.locale, ct.tags, ct.last_seen_at,
       ct.owner_id as contact_owner_id, owner.full_name as contact_owner_name,
       ch.id as channel_id, ch.platform, coalesce(ch.display_name, ch.handle) as channel_name,
       team.name as team_name,
       assignee.full_name as assignee_name, assignee.avatar_url as assignee_avatar,
       last.body, last.type as last_type, last.direction, last.origin, last.transcript,
       last.created_at as last_at,
       (select count(*) from messages unread
         where unread.conversation_id = cv.id and unread.direction = 'in'
           and unread.kind = 'message'
           and unread.created_at > coalesce(reads.last_read_at, '-infinity'::timestamptz)
       ) as unread_count
from conversations cv
join contacts ct on ct.id = cv.contact_id
left join profiles owner on owner.id = ct.owner_id
left join channels ch on ch.id = cv.channel_id
left join teams team on team.id = cv.team_id
left join profiles assignee on assignee.id = cv.assigned_to
left join conversation_reads reads
       on reads.conversation_id = cv.id and reads.user_id = $1
left join lateral (
    select m.body, m.type, m.direction, m.origin, m.transcript, m.created_at
    from messages m
    where m.conversation_id = cv.id and m.kind = 'message'
    order by m.created_at desc limit 1
) last on true
"""


def list_sql(view: View, *, with_cursor: bool) -> str:
    """$1 user, $2 status, $3 search, $4 channel, [$5 $6 $7 cursor], limit last.

    No tenant parameter: the session already carries it and RLS applies it. A
    parameter the SQL does not read is a parameter that drifts.
    """
    # asyncpg refuses a parameter the query never mentions, so the limit takes
    # whichever number is next once the cursor is in or out.
    limit_param = 8 if with_cursor else 5
    return (
        f"{SUMMARY} where ($2 = '' or cv.status = $2) and {VIEW_SQL[view]} {_SEARCH} {_CHANNEL}"
        f" {_AFTER if with_cursor else ''} {_ORDER} limit ${limit_param}"
    )


def one_sql() -> str:
    """The same row, for one conversation. $1 user, $2 conversation."""
    return f"{SUMMARY} where cv.id = $2"


#: One message as the thread draws it. The joins are shared with THREAD so a
#: message never looks different depending on which route answered.
_MESSAGE_SELECT = """
select m.id, m.conversation_id, m.kind, m.type, m.direction, m.origin, m.body, m.media,
       m.transcript, m.location, m.template, m.reactions, m.status, m.error, m.event,
       m.referral, m.created_at, m.reply_to_id,
       m.author_user_id, author.full_name as author_name, author.avatar_url as author_avatar,
       reply.body as reply_body, reply.type as reply_type, reply.transcript as reply_transcript
from messages m
left join profiles author on author.id = m.author_user_id
left join messages reply on reply.id = m.reply_to_id
"""

#: Newest first, so a page walks backwards into the past; the route reverses it,
#: because the screen appends downwards.
#: $1 conversation, $2 cursor time, $3 cursor id, $4 limit.
THREAD = f"""
{_MESSAGE_SELECT}
where m.conversation_id = $1
  and ($2::timestamptz is null or (m.created_at, m.id) < ($2::timestamptz, $3::uuid))
order by m.created_at desc, m.id desc
limit $4
"""

MESSAGE = f"{_MESSAGE_SELECT} where m.id = $1"

COUNTS = """
select count(*) filter (where cv.waiting_since is not null) as waiting,
       coalesce(sum((select count(*) from messages unread
                      where unread.conversation_id = cv.id and unread.direction = 'in'
                        and unread.kind = 'message'
                        and unread.created_at > coalesce(reads.last_read_at,
                                                         '-infinity'::timestamptz))), 0) as unread
from conversations cv
left join conversation_reads reads on reads.conversation_id = cv.id and reads.user_id = $1
where cv.status = 'open' and {view}
"""
