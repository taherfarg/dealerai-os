-- =============================================================================
-- 0012_sales_erasure_everywhere — what the S6 exit run found after erasing a
-- customer: his number, his WhatsApp id, his name and what he wrote, still in
-- a finished whatsapp.message_received event and in the raw webhook bodies.
-- Erasure matched events by our own ids, and only while they were pending;
-- a raw payload names the customer by their identities, and a finished event
-- was never deleted by anything. See docs/sales/02-data-model.md § 7.
-- =============================================================================

create or replace function app.erase_contact(p_contact uuid, p_actor uuid, p_reason text)
returns text[]
language plpgsql
set search_path = public, pg_temp
as $fn$
declare
  v_tenant        uuid;
  v_conversations uuid[];
  v_leads         uuid[];
  v_tasks         uuid[];
  v_ids           text[];
  v_marks         text[];
  v_paths         text[];
begin
  select tenant_id into v_tenant from contacts where id = p_contact for update;
  if v_tenant is null then
    return null;
  end if;

  select coalesce(array_agg(id), '{}') into v_conversations
    from conversations where contact_id = p_contact;
  select coalesce(array_agg(id), '{}') into v_leads
    from leads where contact_id = p_contact;
  select coalesce(array_agg(id), '{}') into v_tasks
    from tasks
   where contact_id = p_contact
      or lead_id = any (v_leads)
      or conversation_id = any (v_conversations);
  v_ids := (v_conversations || v_leads || v_tasks || p_contact)::text[];

  -- How a payload names them: by our ids, or by their identities as the
  -- platform writes them — a number without its plus. Quoted, so a longer
  -- number that contains theirs is not them; long enough to mean somebody.
  select coalesce(array_agg(distinct mark), '{}') into v_marks
    from (select '%' || id || '%' as mark from unnest(v_ids) id
          union all
          select '%"' || candidate || '"%'
            from contact_identities i,
                 lateral (values (i.value), (ltrim(i.value, '+'))) v(candidate)
           where i.contact_id = p_contact and length(candidate) >= 6) marks;

  select coalesce(array_agg(distinct asset->>'storage_path'), '{}') into v_paths
    from messages m
    cross join lateral jsonb_array_elements(m.media) asset
   where m.conversation_id = any (v_conversations)
     and asset->>'storage_path' is not null;

  -- What the models were shown about them: the runs, and their traces with them.
  delete from agent_runs
   where tenant_id = v_tenant
     and (goal_input->>'conversation_id' = any (v_ids)
          or goal_input->>'lead_id' = any (v_ids));
  -- Queued work about them would run against rows that are gone, and finished
  -- work still holds what caused it — the raw inbound message included.
  delete from events where tenant_id = v_tenant and payload::text like any (v_marks);
  -- The raw bodies, including those written before a tenant was known.
  delete from webhook_deliveries
   where (tenant_id = v_tenant or tenant_id is null) and body::text like any (v_marks);
  delete from notifications where entity->>'id' = any (v_ids);
  delete from tasks where id = any (v_tasks);
  -- Messages, reads, drafts and misses go with their conversations.
  delete from conversations where id = any (v_conversations);
  update audit_log set before = null, after = null
   where entity_type = 'contact'
     and (entity_id = p_contact or meta->>'keep_id' = p_contact::text);
  -- Identities, leads and activities go with the contact.
  delete from contacts where id = p_contact;

  insert into audit_log (tenant_id, actor_type, actor_id, action, entity_type, entity_id, meta)
  values (v_tenant,
          case when p_actor is null then 'system' else 'user' end,
          p_actor::text,
          'contact.erased', 'contact', p_contact,
          jsonb_build_object('reason', p_reason));
  return v_paths;
end $fn$;

revoke all on function app.erase_contact(uuid, uuid, text) from public;
grant execute on function app.erase_contact(uuid, uuid, text) to dealerai_app;
