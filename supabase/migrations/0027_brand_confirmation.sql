-- =============================================================================
-- 0027_brand_confirmation — T3.1: a brand profile read from the dealer's own
-- assets is a draft until a person confirms it. See docs/09 § T3.1.
-- =============================================================================

-- "Confirmed" used to mean "has a display name", and app.create_tenant gives
-- every new tenant one — so every profile was confirmed the moment it existed,
-- by nobody. Now it is a person and a time, together or not at all: no write
-- without a user can put a profile in the confirmed state.
alter table brand_profiles
  add column confirmed_at timestamptz,
  -- Who, kept as a record rather than a foreign key: with `on delete set null`
  -- the check below would stop a person who once confirmed a brand from ever
  -- being erased.
  add column confirmed_by uuid,
  -- What the last reading of the dealer's logo, posts and captions proposed,
  -- waiting for a person. Never read by an agent: only confirming moves it
  -- into the columns agents read.
  add column draft        jsonb,
  add column draft_at     timestamptz,
  add constraint brand_profiles_confirmed_by_a_person
    check (confirmed_at is null or confirmed_by is not null);
