BEGIN;

ALTER TABLE public_website_settings
    ADD COLUMN IF NOT EXISTS appointment_contact_email
        VARCHAR(254) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS appointment_contact_phone
        VARCHAR(50) NOT NULL DEFAULT '';

COMMIT;
