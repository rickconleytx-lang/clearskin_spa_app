-- PeachWeb optional public branding initials
-- NULL uses initials derived from the public Website Business Name.
-- Registered business identity remains unchanged.

BEGIN;

ALTER TABLE public.public_website_settings
    ADD COLUMN website_display_initials VARCHAR(4);

ALTER TABLE public.public_website_settings
    ADD CONSTRAINT website_display_initials_format_check
    CHECK (
        website_display_initials IS NULL
        OR website_display_initials ~ '^[A-Z0-9]{1,4}$'
    );

COMMENT ON COLUMN
    public.public_website_settings.website_display_initials
IS 'Optional 1-4 character public initials override; NULL uses automatic initials';

COMMIT;
