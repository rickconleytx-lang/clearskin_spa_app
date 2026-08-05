BEGIN;

-- =========================================================
-- SMS PHONE NUMBER REGISTRY
--
-- Master Admin-managed ownership of provider phone numbers.
-- No phone numbers are inserted by this migration.
-- =========================================================

CREATE TABLE IF NOT EXISTS sms_phone_numbers (
    sms_phone_number_id SERIAL PRIMARY KEY,
    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER,
    provider VARCHAR(50) NOT NULL DEFAULT 'telnyx',
    phone_number VARCHAR(32) NOT NULL,
    messaging_profile_id VARCHAR(255),
    campaign_id VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    created_by INTEGER,
    updated_by INTEGER
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_sms_phone_numbers_spa'
    ) THEN
        ALTER TABLE sms_phone_numbers
        ADD CONSTRAINT fk_sms_phone_numbers_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE CASCADE;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_sms_phone_numbers_business_unit_spa'
    ) THEN
        ALTER TABLE sms_phone_numbers
        ADD CONSTRAINT
            fk_sms_phone_numbers_business_unit_spa
        FOREIGN KEY (business_unit_id, spa_id)
        REFERENCES business_units (
            business_unit_id,
            spa_id
        );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_sms_phone_numbers_created_by'
    ) THEN
        ALTER TABLE sms_phone_numbers
        ADD CONSTRAINT fk_sms_phone_numbers_created_by
        FOREIGN KEY (created_by)
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
        WHERE conname = 'fk_sms_phone_numbers_updated_by'
    ) THEN
        ALTER TABLE sms_phone_numbers
        ADD CONSTRAINT fk_sms_phone_numbers_updated_by
        FOREIGN KEY (updated_by)
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
        WHERE conname = 'chk_sms_phone_numbers_e164'
    ) THEN
        ALTER TABLE sms_phone_numbers
        ADD CONSTRAINT chk_sms_phone_numbers_e164
        CHECK (
            phone_number ~ '^[+][1-9][0-9]{7,14}$'
        );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_sms_phone_numbers_provider_lower'
    ) THEN
        ALTER TABLE sms_phone_numbers
        ADD CONSTRAINT chk_sms_phone_numbers_provider_lower
        CHECK (
            provider = LOWER(provider)
        );
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_sms_phone_numbers_provider_phone
ON sms_phone_numbers (
    provider,
    phone_number
);

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_sms_phone_numbers_id_spa
ON sms_phone_numbers (
    sms_phone_number_id,
    spa_id
);

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_sms_phone_numbers_spa_default
ON sms_phone_numbers (
    spa_id,
    provider
)
WHERE business_unit_id IS NULL
  AND is_active = TRUE
  AND is_default = TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_sms_phone_numbers_workspace_default
ON sms_phone_numbers (
    spa_id,
    business_unit_id,
    provider
)
WHERE business_unit_id IS NOT NULL
  AND is_active = TRUE
  AND is_default = TRUE;

CREATE INDEX IF NOT EXISTS
    idx_sms_phone_numbers_spa_workspace_active
ON sms_phone_numbers (
    spa_id,
    business_unit_id,
    is_active
);

-- =========================================================
-- ACTIVE SMS MESSAGE DELIVERY FIELDS
--
-- Existing records remain valid. New fields remain nullable
-- until provider routing is connected and safely backfilled.
-- =========================================================

ALTER TABLE sms_messages
    ADD COLUMN IF NOT EXISTS sms_phone_number_id INTEGER,
    ADD COLUMN IF NOT EXISTS sender_phone VARCHAR(32),
    ADD COLUMN IF NOT EXISTS receiving_phone VARCHAR(32),
    ADD COLUMN IF NOT EXISTS provider_received_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS provider_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS provider_completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at
        TIMESTAMP WITHOUT TIME ZONE;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_sms_messages_phone_number_spa'
    ) THEN
        ALTER TABLE sms_messages
        ADD CONSTRAINT fk_sms_messages_phone_number_spa
        FOREIGN KEY (
            sms_phone_number_id,
            spa_id
        )
        REFERENCES sms_phone_numbers (
            sms_phone_number_id,
            spa_id
        );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS
    idx_sms_messages_provider_message_id
ON sms_messages (
    provider_message_id
)
WHERE provider_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS
    idx_sms_messages_phone_number_id
ON sms_messages (
    sms_phone_number_id
)
WHERE sms_phone_number_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS
    idx_sms_messages_sender_phone
ON sms_messages (
    sender_phone
)
WHERE sender_phone IS NOT NULL;

CREATE INDEX IF NOT EXISTS
    idx_sms_messages_receiving_phone
ON sms_messages (
    receiving_phone
)
WHERE receiving_phone IS NOT NULL;

-- =========================================================
-- TELNYX WEBHOOK EVENT LOG
--
-- Reuse and strengthen the existing empty table.
-- spa_id remains nullable so events for unknown numbers can
-- be retained as unrouted instead of assigned incorrectly.
-- =========================================================

ALTER TABLE telnyx_webhook_log
    ALTER COLUMN spa_id DROP NOT NULL;

ALTER TABLE telnyx_webhook_log
    ADD COLUMN IF NOT EXISTS business_unit_id INTEGER,
    ADD COLUMN IF NOT EXISTS sms_phone_number_id INTEGER,
    ADD COLUMN IF NOT EXISTS sms_message_id INTEGER,
    ADD COLUMN IF NOT EXISTS provider
        VARCHAR(50) NOT NULL DEFAULT 'telnyx',
    ADD COLUMN IF NOT EXISTS provider_message_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS sender_phone VARCHAR(32),
    ADD COLUMN IF NOT EXISTS receiving_phone VARCHAR(32),
    ADD COLUMN IF NOT EXISTS messaging_profile_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS delivery_attempt INTEGER,
    ADD COLUMN IF NOT EXISTS event_occurred_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS signature_verified
        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS receive_count
        INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS last_received_at
        TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE telnyx_webhook_log
SET processing_status = LOWER(
        COALESCE(processing_status, 'received')
    ),
    is_processed = COALESCE(is_processed, FALSE),
    received_at = COALESCE(
        received_at,
        CURRENT_TIMESTAMP
    ),
    created_at = COALESCE(
        created_at,
        CURRENT_TIMESTAMP
    ),
    last_received_at = COALESCE(
        last_received_at,
        received_at,
        CURRENT_TIMESTAMP
    ),
    receive_count = COALESCE(receive_count, 1);

ALTER TABLE telnyx_webhook_log
    ALTER COLUMN processing_status
        SET DEFAULT 'received',
    ALTER COLUMN processing_status
        SET NOT NULL,
    ALTER COLUMN is_processed
        SET DEFAULT FALSE,
    ALTER COLUMN is_processed
        SET NOT NULL,
    ALTER COLUMN received_at
        SET DEFAULT CURRENT_TIMESTAMP,
    ALTER COLUMN received_at
        SET NOT NULL,
    ALTER COLUMN created_at
        SET DEFAULT CURRENT_TIMESTAMP,
    ALTER COLUMN created_at
        SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_telnyx_webhook_log_spa'
    ) THEN
        ALTER TABLE telnyx_webhook_log
        ADD CONSTRAINT fk_telnyx_webhook_log_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
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
            'fk_telnyx_webhook_log_business_unit_spa'
    ) THEN
        ALTER TABLE telnyx_webhook_log
        ADD CONSTRAINT
            fk_telnyx_webhook_log_business_unit_spa
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_telnyx_webhook_log_phone_number_spa'
    ) THEN
        ALTER TABLE telnyx_webhook_log
        ADD CONSTRAINT
            fk_telnyx_webhook_log_phone_number_spa
        FOREIGN KEY (
            sms_phone_number_id,
            spa_id
        )
        REFERENCES sms_phone_numbers (
            sms_phone_number_id,
            spa_id
        );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_telnyx_webhook_log_sms_message'
    ) THEN
        ALTER TABLE telnyx_webhook_log
        ADD CONSTRAINT
            fk_telnyx_webhook_log_sms_message
        FOREIGN KEY (sms_message_id)
        REFERENCES sms_messages(sms_message_id)
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
            'chk_telnyx_webhook_workspace_requires_spa'
    ) THEN
        ALTER TABLE telnyx_webhook_log
        ADD CONSTRAINT
            chk_telnyx_webhook_workspace_requires_spa
        CHECK (
            business_unit_id IS NULL
            OR spa_id IS NOT NULL
        );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'chk_telnyx_webhook_phone_requires_spa'
    ) THEN
        ALTER TABLE telnyx_webhook_log
        ADD CONSTRAINT
            chk_telnyx_webhook_phone_requires_spa
        CHECK (
            sms_phone_number_id IS NULL
            OR spa_id IS NOT NULL
        );
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_telnyx_webhook_log_event_id
ON telnyx_webhook_log (
    telnyx_event_id
)
WHERE telnyx_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS
    idx_telnyx_webhook_log_provider_message
ON telnyx_webhook_log (
    provider_message_id
)
WHERE provider_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS
    idx_telnyx_webhook_log_receiving_phone
ON telnyx_webhook_log (
    receiving_phone
)
WHERE receiving_phone IS NOT NULL;

CREATE INDEX IF NOT EXISTS
    idx_telnyx_webhook_log_processing
ON telnyx_webhook_log (
    processing_status,
    received_at DESC
);

CREATE INDEX IF NOT EXISTS
    idx_telnyx_webhook_log_workspace_received
ON telnyx_webhook_log (
    spa_id,
    business_unit_id,
    received_at DESC
);

COMMIT;
