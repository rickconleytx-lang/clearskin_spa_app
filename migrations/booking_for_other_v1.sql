BEGIN;

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS booking_for_other
        BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS service_recipient_client_id
        INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'appointments_service_recipient_client_id_fkey'
    ) THEN
        ALTER TABLE appointments
            ADD CONSTRAINT
                appointments_service_recipient_client_id_fkey
            FOREIGN KEY (
                service_recipient_client_id
            )
            REFERENCES clients(client_id)
            ON DELETE SET NULL;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS
    idx_appointments_service_recipient_client
    ON appointments (
        spa_id,
        service_recipient_client_id
    )
    WHERE service_recipient_client_id IS NOT NULL;

COMMIT;
