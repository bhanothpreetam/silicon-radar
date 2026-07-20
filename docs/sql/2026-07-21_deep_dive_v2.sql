-- Silicon Radar vNext: structured analyst/research deep dives.
-- Apply manually in the Supabase SQL editor before setting
-- INTELLIGENCE_PROMPT_VERSION=v2 in any pipeline environment.

ALTER TABLE intelligence_cards
    ADD COLUMN IF NOT EXISTS deep_dive JSONB;

COMMENT ON COLUMN intelligence_cards.deep_dive IS
    'Structured v2 long-form analysis rendered by the Mini App Read more view';
