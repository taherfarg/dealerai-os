"""The CRM's SQL, in one place: customers, their timeline, leads and tasks.

The same rule as the inbox's queries — every statement here runs inside a
`tenant_session`, so the policies do the filtering and no query repeats it.
"""

from __future__ import annotations

#: One customer row. `band` is the best open lead's, because the question the
#: list answers is "who is worth calling today".
CUSTOMER_SELECT = """
select c.id, c.full_name, c.locale as language, c.country, c.tags, c.owner_id, c.team_id,
       c.consent, c.last_seen_at, c.profile, c.profile_updated_at,
       p.full_name as owner_name,
       (select i.value from contact_identities i
         where i.contact_id = c.id and i.kind = 'phone'
         order by i.is_primary desc limit 1) as phone,
       (select l.intent_band from leads l
          join pipeline_stages s on s.id = l.stage_id
         where l.contact_id = c.id and s.category = 'open'
         order by l.score desc nulls last limit 1) as band
  from contacts c
  left join profiles p on p.id = c.owner_id
"""


def list_sql(*, with_cursor: bool) -> str:
    """Newest-seen first, keyed on (last_seen_at, id).

    The tuple comparison is what stops a cursor skipping a row when two
    customers share a timestamp — the same rule as the inbox's cursor. The
    limit's parameter number moves with the cursor because asyncpg refuses a
    statement that declares a parameter it never uses.
    """
    cursor = "and (c.last_seen_at, c.id) < ($5::timestamptz, $6::uuid)" if with_cursor else ""
    limit = "$7" if with_cursor else "$5"
    return f"""
{CUSTOMER_SELECT}
 where ($1::text is null
        or c.full_name ilike '%' || $1 || '%'
        or exists (select 1 from contact_identities i
                    where i.contact_id = c.id and i.value ilike '%' || $1 || '%'))
   and ($2::uuid is null or c.owner_id = $2)
   and ($3::text is null or c.country = $3)
   and ($4::text is null or $4 = any (c.tags))
   {cursor}
 order by c.last_seen_at desc, c.id desc
 limit {limit}
"""


ONE_CUSTOMER = f"{CUSTOMER_SELECT} where c.id = $1"

IDENTITIES = """
select id, kind, value, is_primary from contact_identities
 where contact_id = $1 order by kind, is_primary desc, value
"""

#: One lead, everywhere a lead is shown: the board's card, the customer panel
#: and the drawer. `next_action_at` is the earliest open task, computed rather
#: than stored, which is why leads.next_action_at was dropped.
LEAD_SELECT = """
select l.id, l.contact_id, ct.full_name as contact_name, ct.country as contact_country,
       l.score, l.intent_band, l.score_signals, l.budget_minor, l.currency,
       l.stage_entered_at, l.conversation_id, l.lost_reason, l.source, l.created_at,
       l.pipeline_id, pl.name as pipeline_name,
       l.stage_id, s.name as stage_name, s.category as stage_category,
       l.vehicle_id, v.make, v.model, v.model_year,
       l.owner_id, o.full_name as owner_name,
       (select min(t.due_at) from tasks t
         where t.lead_id = l.id and t.status = 'open') as next_action_at
  from leads l
  join contacts ct on ct.id = l.contact_id
  join pipeline_stages s on s.id = l.stage_id
  join pipelines pl on pl.id = l.pipeline_id
  left join vehicles v on v.id = l.vehicle_id
  left join profiles o on o.id = l.owner_id
"""

#: The customer panel and the 360. $2 true asks for open leads only.
OPEN_LEADS = f"""
{LEAD_SELECT}
 where l.contact_id = $1 and ($2::boolean is not true or s.category = 'open')
 order by s.category, l.score desc nulls last, l.created_at desc
"""

#: The board, in board order: the column, then the best lead in it.
LEADS_LIST = f"""
{LEAD_SELECT}
 where ($1::uuid is null or l.pipeline_id = $1)
   and ($2::uuid is null or l.owner_id = $2)
   and ($3::text is null or l.intent_band = $3)
   and ($4::text is null or ct.full_name ilike '%' || $4 || '%')
 order by s.position, l.score desc nulls last, l.created_at desc
 limit $5
"""

ONE_LEAD = f"{LEAD_SELECT} where l.id = $1"

#: Where it has been. Written by the API on every stage move, read by the drawer.
STAGE_HISTORY = """
select a.occurs_at, a.body, a.meta, p.full_name as actor_name
  from activities a
  left join profiles p on p.id::text = a.actor_id
 where a.lead_id = $1 and a.kind = 'stage_change'
 order by a.occurs_at desc
"""

LEAD_TASKS = """
select t.id, t.title, t.kind, t.due_at, t.status, t.assignee_id,
       p.full_name as assignee_name
  from tasks t
  left join profiles p on p.id = t.assignee_id
 where t.lead_id = $1
 order by t.status, t.due_at
"""

OPEN_TASK_COUNT = "select count(*) from tasks where contact_id = $1 and status = 'open'"

#: Everything that happened with this customer, newest first, from both the
#: conversations and the lead history. Offset paging rather than a keyset: it
#: merges two tables whose ids are different types, and a customer with more
#: than a few hundred rows is a customer nobody scrolls to the end of.
#: ponytail: swap for a keyset if a timeline ever needs page twenty.
TIMELINE = """
select 'message' as kind, m.id::text as id, m.created_at as at,
       jsonb_build_object(
         'conversation_id', m.conversation_id, 'direction', m.direction, 'message_kind', m.kind,
         'type', m.type, 'origin', m.origin, 'body', m.body, 'transcript', m.transcript,
         'event', m.event, 'author', a.full_name, 'status', m.status
       ) as data
  from messages m
  join conversations c on c.id = m.conversation_id
  left join profiles a on a.id = m.author_user_id
 where c.contact_id = $1
union all
select 'activity', act.id::text, act.occurs_at,
       jsonb_build_object('activity_kind', act.kind, 'body', act.body, 'meta', act.meta)
  from activities act
 where act.contact_id = $1
    or act.lead_id in (select id from leads where contact_id = $1)
 order by at desc, id desc
 limit $2 offset $3
"""

#: Where a customer went, for a link somebody saved before the merge.
MERGED_INTO = """
select meta->>'keep_id' from audit_log
 where tenant_id = $1 and action = 'contact.merged'
   and entity_type = 'contact' and entity_id = $2
 order by created_at desc limit 1
"""
