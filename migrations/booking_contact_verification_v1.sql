BEGIN;

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS contact_verification_type VARCHAR(40);

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS booking_contact_name_submitted VARCHAR(170);

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS booking_contact_email_submitted VARCHAR(150);

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS booking_contact_phone_submitted VARCHAR(30);

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS contact_verification_resolved BOOLEAN
        NOT NULL DEFAULT FALSE;

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS contact_verification_resolved_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS
    idx_appointments_contact_verification_pending
ON appointments (
    spa_id,
    business_unit_id,
    appointment_date
)
WHERE contact_verification_type IS NOT NULL
  AND contact_verification_resolved = FALSE;

COMMIT;
