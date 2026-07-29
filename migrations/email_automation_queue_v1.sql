BEGIN;

CREATE TABLE IF NOT EXISTS email_queue (
    email_queue_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL
        REFERENCES spas(spa_id),

    business_unit_id INTEGER NOT NULL
        REFERENCES business_units(business_unit_id),

    client_id INTEGER
        REFERENCES clients(client_id)
        ON DELETE SET NULL,

    appointment_id INTEGER
        REFERENCES appointments(appointment_id)
        ON DELETE SET NULL,

    email_type VARCHAR(80) NOT NULL,

    recipient_email VARCHAR(255) NOT NULL,
    recipient_name VARCHAR(180),

    subject_line VARCHAR(255) NOT NULL,
    text_body TEXT NOT NULL,
    html_body TEXT,

    status VARCHAR(30) NOT NULL DEFAULT 'pending',

    scheduled_for TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    next_attempt_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    attempt_count INTEGER NOT NULL DEFAULT 0,
    maximum_attempts INTEGER NOT NULL DEFAULT 3,

    last_attempt_at TIMESTAMP WITHOUT TIME ZONE,
    sent_at TIMESTAMP WITHOUT TIME ZONE,

    provider_message_id VARCHAR(255),
    provider_status VARCHAR(100),
    error_message TEXT,

    created_by INTEGER,
    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT email_queue_status_check
        CHECK (
            status IN (
                'pending',
                'processing',
                'sent',
                'failed',
                'cancelled'
            )
        ),

    CONSTRAINT email_queue_attempt_count_check
        CHECK (attempt_count >= 0),

    CONSTRAINT email_queue_maximum_attempts_check
        CHECK (maximum_attempts >= 1),

    CONSTRAINT email_queue_recipient_check
        CHECK (TRIM(recipient_email) <> ''),

    CONSTRAINT email_queue_subject_check
        CHECK (TRIM(subject_line) <> '')
);


CREATE INDEX IF NOT EXISTS idx_email_queue_ready
    ON email_queue (
        status,
        next_attempt_at,
        scheduled_for
    );


CREATE INDEX IF NOT EXISTS idx_email_queue_workspace
    ON email_queue (
        spa_id,
        business_unit_id,
        created_at DESC
    );


CREATE INDEX IF NOT EXISTS idx_email_queue_client
    ON email_queue (
        spa_id,
        client_id,
        created_at DESC
    )
    WHERE client_id IS NOT NULL;


CREATE INDEX IF NOT EXISTS idx_email_queue_appointment
    ON email_queue (
        spa_id,
        appointment_id,
        created_at DESC
    )
    WHERE appointment_id IS NOT NULL;


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_email_queue_appointment_type
    ON email_queue (
        spa_id,
        business_unit_id,
        appointment_id,
        email_type
    )
    WHERE appointment_id IS NOT NULL;


COMMIT;
