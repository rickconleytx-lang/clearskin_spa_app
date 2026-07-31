-- =========================================================
-- APPOINTMENT-SPECIFIC TODAY'S CONTACT
-- Blank/NULL values fall back to the client information.
-- =========================================================

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS
        todays_contact_name VARCHAR(150);

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS
        todays_contact_phone VARCHAR(50);

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS
        todays_contact_note TEXT;
