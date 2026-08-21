BEGIN;

-- =========================================================
-- PEACHBOOK BOOKING NOTIFICATIONS
--
-- One notification configuration per Provider Workspace.
-- Existing workspaces default to notifications off.
-- =========================================================

ALTER TABLE booking_settings
    ADD COLUMN IF NOT EXISTS
        booking_notification_preference VARCHAR(16)
        NOT NULL DEFAULT 'off',

    ADD COLUMN IF NOT EXISTS
        booking_notification_email VARCHAR(320),

    ADD COLUMN IF NOT EXISTS
        booking_notification_phone VARCHAR(32),

    ADD COLUMN IF NOT EXISTS
        booking_notification_sms_consent BOOLEAN
        NOT NULL DEFAULT FALSE,

    ADD COLUMN IF NOT EXISTS
        booking_notification_sms_consent_at
        TIMESTAMP WITHOUT TIME ZONE,

    ADD COLUMN IF NOT EXISTS
        booking_notification_sms_consent_by INTEGER,

    ADD COLUMN IF NOT EXISTS
        booking_notification_sms_consent_version VARCHAR(64);


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_booking_notification_sms_consent_by'
          AND conrelid =
                'booking_settings'::regclass
    ) THEN
        ALTER TABLE booking_settings
        ADD CONSTRAINT
            fk_booking_notification_sms_consent_by
        FOREIGN KEY (
            booking_notification_sms_consent_by
        )
        REFERENCES users(user_id)
        ON DELETE SET NULL;
    END IF;
END
$$;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'chk_booking_notification_preference'
          AND conrelid =
                'booking_settings'::regclass
    ) THEN
        ALTER TABLE booking_settings
        ADD CONSTRAINT
            chk_booking_notification_preference
        CHECK (
            booking_notification_preference IN (
                'off',
                'email',
                'sms',
                'both'
            )
        );
    END IF;
END
$$;

-- =========================================================
-- BOOKING NOTIFICATION DELIVERY GUARD
--
-- One row per workspace / appointment / channel.
-- The row is claimed before an external notification send so
-- a repeated booking request cannot send the same channel twice.
-- =========================================================

CREATE TABLE IF NOT EXISTS booking_notification_deliveries (
    booking_notification_delivery_id BIGSERIAL
        PRIMARY KEY,

    spa_id INTEGER NOT NULL,

    business_unit_id INTEGER NOT NULL,

    appointment_id INTEGER NOT NULL,

    channel VARCHAR(16) NOT NULL,

    destination VARCHAR(320),

    status VARCHAR(24)
        NOT NULL DEFAULT 'pending',

    provider_message_id VARCHAR(255),

    last_error TEXT,

    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    attempted_at TIMESTAMP WITHOUT TIME ZONE,

    sent_at TIMESTAMP WITHOUT TIME ZONE,

    updated_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_booking_notification_delivery_appointment
        FOREIGN KEY (
            appointment_id,
            spa_id,
            business_unit_id
        )
        REFERENCES appointments (
            appointment_id,
            spa_id,
            business_unit_id
        )
        ON DELETE CASCADE,

    CONSTRAINT chk_booking_notification_delivery_channel
        CHECK (
            channel IN (
                'email',
                'sms'
            )
        ),

    CONSTRAINT chk_booking_notification_delivery_status
        CHECK (
            status IN (
                'pending',
                'attempting',
                'queued',
                'sent',
                'failed'
            )
        ),

    CONSTRAINT uq_booking_notification_delivery
        UNIQUE (
            spa_id,
            business_unit_id,
            appointment_id,
            channel
        )
);


COMMIT;
