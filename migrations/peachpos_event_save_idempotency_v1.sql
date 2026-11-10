BEGIN;

-- ==========================================================
-- PEACH SUITE PRO
-- PEACHPOS EVENT SAVE IDEMPOTENCY V1
--
-- Durable identity for each Event Calendar save submission.
-- The submission and all event records must commit together.
--
-- This table is not used for appointment Income or Payroll.
-- ==========================================================

CREATE TABLE event_calendar_save_submissions (

    submission_token UUID PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    request_sha256 VARCHAR(64) NOT NULL,

    event_id BIGINT,

    created_by INTEGER,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    completed_at TIMESTAMPTZ,

    CONSTRAINT fk_event_save_submission_workspace
        FOREIGN KEY (spa_id, business_unit_id)
        REFERENCES business_units (
            spa_id,
            business_unit_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_event_save_submission_event
        FOREIGN KEY (spa_id, business_unit_id, event_id)
        REFERENCES event_calendar_events (
            spa_id,
            business_unit_id,
            event_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_event_save_submission_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT chk_event_save_submission_hash
        CHECK (
            request_sha256 ~ '^[0-9a-f]{64}$'
        ),

    CONSTRAINT chk_event_save_submission_completion
        CHECK (
            (
                event_id IS NULL
                AND completed_at IS NULL
            )
            OR
            (
                event_id IS NOT NULL
                AND completed_at IS NOT NULL
            )
        ),

    CONSTRAINT uq_event_save_submission_event
        UNIQUE (spa_id, business_unit_id, event_id)
);

CREATE INDEX idx_event_save_submission_workspace
    ON event_calendar_save_submissions (
        spa_id,
        business_unit_id,
        created_at DESC
    );

COMMENT ON TABLE event_calendar_save_submissions IS
    'Durable PeachPOS Event Calendar save identities. '
    'The submission token prevents repeated event creation. '
    'Submission completion and event creation commit atomically.';

COMMENT ON COLUMN
    event_calendar_save_submissions.request_sha256 IS
    'SHA-256 fingerprint of the submitted event request. '
    'Detects reuse of a token with changed content.';

COMMIT;
