BEGIN;

ALTER TABLE public_website_settings
    ADD COLUMN IF NOT EXISTS show_promotional_section
        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS promotional_heading
        VARCHAR(180) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS promotional_text
        TEXT NOT NULL DEFAULT '';

COMMIT;
