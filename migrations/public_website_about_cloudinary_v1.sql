BEGIN;

ALTER TABLE public_website_settings
    ADD COLUMN IF NOT EXISTS about_image_public_id TEXT;

COMMIT;
