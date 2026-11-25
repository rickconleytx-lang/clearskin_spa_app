-- PeachWeb Events & Locations Settings V1
--
-- Additive website settings only.
-- No changes to Event Calendar tables.
-- Existing businesses default to publication OFF.
-- Migration requires separate database review and backup.

BEGIN;

ALTER TABLE public.public_website_settings

    ADD COLUMN IF NOT EXISTS
        show_events_locations
        BOOLEAN NOT NULL DEFAULT FALSE,

    ADD COLUMN IF NOT EXISTS
        events_locations_heading
        VARCHAR(180) NOT NULL DEFAULT 'Where to Find Us',

    ADD COLUMN IF NOT EXISTS
        events_locations_intro
        TEXT NOT NULL DEFAULT
        'Find our food trucks at these upcoming events and locations!',

    ADD COLUMN IF NOT EXISTS
        events_locations_show_directions
        BOOLEAN NOT NULL DEFAULT TRUE,

    ADD COLUMN IF NOT EXISTS
        events_locations_show_daily_hours
        BOOLEAN NOT NULL DEFAULT TRUE;

COMMIT;
