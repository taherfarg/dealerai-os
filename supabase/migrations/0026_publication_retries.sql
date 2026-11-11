-- =============================================================================
-- 0026_publication_retries — T4.3: each account waits its own time before it
-- is tried again. See docs/09-implementation-plan.md.
-- =============================================================================

-- A rate-limited Instagram asks for its own wait; a Facebook that timed out
-- may be tried sooner. One time for the piece would try Instagram at
-- Facebook's, and spend its tries before its wait was up. Null when the row is
-- not waiting.
alter table publications add column retry_at timestamptz;
