BEGIN;

ALTER TABLE public_website_settings
    ADD COLUMN IF NOT EXISTS
        website_color_scheme
        VARCHAR(50) NOT NULL
        DEFAULT 'peach_cream';

COMMIT;
