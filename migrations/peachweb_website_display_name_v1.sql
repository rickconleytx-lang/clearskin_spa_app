-- PeachWeb Website Display Name v1
-- Optional public-facing business name.
-- NULL means use the registered business name.
-- Does not change registered business or billing records.

BEGIN;

ALTER TABLE public.public_website_settings
    ADD COLUMN website_display_name VARCHAR(180);

COMMENT ON COLUMN
    public.public_website_settings.website_display_name
IS 'Optional public website branding name; NULL uses registered business name';

COMMIT;
