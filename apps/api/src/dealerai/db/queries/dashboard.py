"""Every number the manager's dashboard and the morning brief show.

No visibility here, on purpose, as in queries/inbox.py: the caller's session
already decided which rows exist, so a manager's counts are her teams' because
Postgres shows her nothing else. A count that filtered by team itself would be
a second definition of "her teams" — the one that drifts.
"""

from __future__ import annotations

#: $1 since, $2 until. Every conversation first answered in the window: who
#: answered, when, and when the customer *first* wrote — somebody who wrote
#: at 10:00 and again at 10:30 had waited half an hour at 10:31, not a minute.
ANSWERED = """
select c.assigned_to, c.first_response_at as answered_at,
       (select min(m.created_at) from messages m
         where m.conversation_id = c.id and m.direction = 'in' and m.kind = 'message'
           and m.created_at <= c.first_response_at) as asked_at
  from conversations c
 where c.first_response_at >= $1 and c.first_response_at < $2
"""

#: $1 since, $2 until (the day shown), $3 now. The windowed counts are that
#: day's; waiting, hot and overdue are the state of things now.
FACTS = """
select
  (select count(*) from conversations
    where created_at >= $1 and created_at < $2)                               as new_conversations,
  (select count(*) from conversations
    where status = 'open' and waiting_since is not null)                      as waiting_now,
  (select count(*) from conversations
    where status = 'open' and waiting_since is not null
      and sla_due_at < $3) as waiting_past_target,
  (select count(*) from sla_misses where due_at >= $1 and due_at < $2)        as missed_targets,
  (select count(*) from leads where created_at >= $1 and created_at < $2)     as new_leads,
  (select count(*) from leads l join pipeline_stages s on s.id = l.stage_id
    where s.category = 'open' and l.intent_band = 'hot')                      as hot_leads,
  (select count(*) from leads l join pipeline_stages s on s.id = l.stage_id
    where s.category = 'open' and l.intent_band = 'hot'
      and not exists (select 1 from tasks t
                       where t.lead_id = l.id and t.status = 'open')) as hot_without_next_step,
  (select count(*) from leads l join pipeline_stages s on s.id = l.stage_id
    where s.category = 'won' and l.stage_entered_at >= $1
      and l.stage_entered_at < $2)                                            as won,
  (select count(*) from leads l join pipeline_stages s on s.id = l.stage_id
    where s.category = 'lost' and l.stage_entered_at >= $1
      and l.stage_entered_at < $2)                                            as lost,
  (select count(*) from tasks where status = 'open' and due_at < $3)          as overdue_tasks,
  (select count(*) from messages
    where direction = 'out' and kind = 'message' and origin in ('inbox', 'ai')
      and created_at >= $1 and created_at < $2)                               as replies_inbox,
  (select count(*) from messages
    where direction = 'out' and kind = 'message' and origin = 'phone_app'
      and created_at >= $1 and created_at < $2)                               as replies_phone
"""

#: $1 tenant, $2 since, $3 until, $4 now, $5 the month's start. The people a
#: manager manages: everyone in sales for an owner, her teams' members for her.
#: Memberships have no owner column, so this is the one query that names the
#: scope — through the same app.my_team_ids() the policies use.
TEAM = """
select m.user_id as id, p.full_name as name,
       (select count(*) from conversations c
         where c.assigned_to = m.user_id and c.status = 'open')              as open,
       (select count(*) from conversations c
         where c.assigned_to = m.user_id and c.status = 'open'
           and c.waiting_since is not null)                                   as waiting,
       (select count(*) from sla_misses s
         where s.assigned_to = m.user_id and s.due_at >= $2 and s.due_at < $3) as missed_targets,
       (select count(*) from tasks t
         where t.assignee_id = m.user_id and t.status = 'open' and t.due_at < $4) as overdue_tasks,
       coalesce(bands.hot, 0) as hot, coalesce(bands.warm, 0) as warm,
       coalesce(bands.cold, 0) as cold, coalesce(bands.won_this_month, 0) as won_this_month
  from memberships m
  left join profiles p on p.id = m.user_id
  left join lateral (
    select count(*) filter (where s.category = 'open' and l.intent_band = 'hot')  as hot,
           count(*) filter (where s.category = 'open' and l.intent_band = 'warm') as warm,
           count(*) filter (where s.category = 'open' and l.intent_band = 'cold') as cold,
           count(*) filter (where s.category = 'won' and l.stage_entered_at >= $5) as won_this_month
      from leads l join pipeline_stages s on s.id = l.stage_id
     where l.owner_id = m.user_id
  ) bands on true
 where m.tenant_id = $1 and m.role in ('sales', 'manager')
   and (current_setting('app.scope', true) = 'all'
        or exists (select 1 from team_members tm
                    where tm.user_id = m.user_id
                      and tm.team_id = any (coalesce((select app.my_team_ids()), '{}'))))
 order by p.full_name nulls last
"""

#: Open leads per stage, every board, in board order.
PIPELINE = """
select p.id as pipeline_id, p.name as pipeline_name, s.id as stage_id, s.name as stage_name,
       count(l.id) as leads
  from pipelines p
  join pipeline_stages s on s.pipeline_id = p.id and s.category = 'open'
  left join leads l on l.stage_id = s.id
 group by p.id, p.name, p.is_default, p.position, s.id, s.name, s.position
 order by p.is_default desc, p.position, s.position
"""

#: $1 since: where the last thirty days' leads came from.
SOURCES = """
select coalesce(source, 'unknown') as source, count(*) as leads
  from leads where created_at >= $1
 group by 1 order by 2 desc, 1
"""

#: $1 two weeks ago, $2 one week ago. Replies typed in the inbox against
#: replies typed on the phone (docs/sales/00-prd.md S8: rising week over week).
SHARE = """
select count(*) filter (where origin in ('inbox', 'ai') and created_at >= $2) as inbox_this_week,
       count(*) filter (where origin = 'phone_app' and created_at >= $2)      as phone_this_week,
       count(*) filter (where origin in ('inbox', 'ai') and created_at < $2)  as inbox_last_week,
       count(*) filter (where origin = 'phone_app' and created_at < $2)       as phone_last_week
  from messages
 where direction = 'out' and kind = 'message' and created_at >= $1
"""

#: The three kinds of trouble the brief lists, each shaped the same:
#: id, name, since, owner_id, owner_name, count.
#: $1 now, $2 limit: customers past their target, the longest wait first.
ATTENTION_WAITS = """
select c.id, ct.full_name as name, c.waiting_since as since,
       c.assigned_to as owner_id, p.full_name as owner_name, null::bigint as count
  from conversations c
  join contacts ct on ct.id = c.contact_id
  left join profiles p on p.id = c.assigned_to
 where c.status = 'open' and c.waiting_since is not null and c.sla_due_at < $1
 order by c.waiting_since
 limit $2
"""

#: $1 limit: hot, open, and nobody has anything to do about them.
ATTENTION_HOT = """
select l.id, ct.full_name as name, l.stage_entered_at as since,
       l.owner_id, p.full_name as owner_name, null::bigint as count
  from leads l
  join pipeline_stages s on s.id = l.stage_id and s.category = 'open'
  join contacts ct on ct.id = l.contact_id
  left join profiles p on p.id = l.owner_id
 where l.intent_band = 'hot'
   and not exists (select 1 from tasks t where t.lead_id = l.id and t.status = 'open')
 order by l.score desc nulls last, l.stage_entered_at
 limit $1
"""

#: $1 now, $2 limit: whoever has most tasks past due. Two or more — one late
#: task is a Tuesday.
ATTENTION_OVERDUE = """
select t.assignee_id as id, p.full_name as name, min(t.due_at) as since,
       null::uuid as owner_id, null::text as owner_name, count(*) as count
  from tasks t
  left join profiles p on p.id = t.assignee_id
 where t.status = 'open' and t.due_at < $1
 group by t.assignee_id, p.full_name
having count(*) >= 2
 order by count(*) desc, min(t.due_at)
 limit $2
"""

#: $1 since, $2 until: the cars the copilot's drafts were built on most often —
#: the chips _sources() writes (events/handlers/copilot.py).
MOST_ASKED = """
select source->>'label' as car, count(*) as times
  from ai_suggestions s
  cross join lateral jsonb_array_elements(s.sources) source
 where s.created_at >= $1 and s.created_at < $2 and source->>'kind' = 'vehicle'
 group by 1
 order by 2 desc, 1
 limit 3
"""
