-- =========================================================
-- PEACH SUITE PRO
-- SUPPORT CENTER LANGUAGE CODES V1
--
-- Purpose:
--   Enforce the Peach Suite Pro Help / Support Center product
--   decision that supported Help languages are English and Spanish.
--
-- Notes:
--   - Existing NULL help_pages.language_code values remain permitted
--     for legacy compatibility.
--   - Non-NULL Help language values must use canonical EN or ES.
--   - Support category translations must use canonical EN or ES.
--   - This migration does not modify existing Help content.
-- =========================================================

BEGIN;


DO $$
BEGIN

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'help_pages'::regclass
          AND conname = 'chk_help_pages_language_code'
    ) THEN

        ALTER TABLE help_pages
        ADD CONSTRAINT chk_help_pages_language_code
        CHECK (
            language_code IS NULL
            OR language_code IN (
                'EN',
                'ES'
            )
        );

    END IF;

END
$$;


DO $$
BEGIN

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid =
            'help_category_translations'::regclass
          AND conname =
            'chk_help_category_translations_language_code'
    ) THEN

        ALTER TABLE help_category_translations
        ADD CONSTRAINT
            chk_help_category_translations_language_code
        CHECK (
            language_code IN (
                'EN',
                'ES'
            )
        );

    END IF;

END
$$;


COMMIT;
