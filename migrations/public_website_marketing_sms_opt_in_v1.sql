BEGIN;

ALTER TABLE public_website_settings
    ADD COLUMN IF NOT EXISTS
        include_marketing_sms_in_10dlc_application
        BOOLEAN NOT NULL DEFAULT FALSE;

COMMIT;
