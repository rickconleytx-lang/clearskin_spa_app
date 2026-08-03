BEGIN;

ALTER TABLE service_name_types
    ADD COLUMN IF NOT EXISTS public_description TEXT,
    ADD COLUMN IF NOT EXISTS show_on_public_website BOOLEAN
        NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS website_sort_order INTEGER;

COMMIT;
