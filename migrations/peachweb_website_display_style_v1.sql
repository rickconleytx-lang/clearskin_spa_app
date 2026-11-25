-- PeachWeb Website Display Style v1
-- Business-level setting for PeachPOS website presentation.
-- Existing content is preserved.
-- Solo and Team rendering behavior remains unchanged.

BEGIN;

ALTER TABLE public.public_website_settings
    ADD COLUMN website_display_style VARCHAR(16)
        NOT NULL DEFAULT 'general'
        CONSTRAINT public_website_settings_display_style_check
        CHECK (
            website_display_style IN (
                'general',
                'food',
                'retail'
            )
        );

COMMIT;
