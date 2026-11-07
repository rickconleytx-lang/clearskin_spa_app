BEGIN;

-- Peach Suite Pro
-- Business Preferred Calendar V1
--
-- NULL = use the subscription's default calendar.
-- appointment = Appointment Calendar
-- event = Event Calendar
--
-- This setting does not control entitlements.
-- It does not delete, convert, or modify calendar records.

ALTER TABLE spas
ADD COLUMN IF NOT EXISTS
    preferred_calendar_type VARCHAR(20);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_spas_preferred_calendar_type'
          AND conrelid = 'spas'::regclass
    ) THEN
        ALTER TABLE spas
        ADD CONSTRAINT chk_spas_preferred_calendar_type
        CHECK (
            preferred_calendar_type IN (
                'appointment',
                'event'
            )
        );
    END IF;
END
$$;

COMMIT;
