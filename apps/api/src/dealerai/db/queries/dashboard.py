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
