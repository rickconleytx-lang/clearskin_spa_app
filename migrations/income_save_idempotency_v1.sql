BEGIN;

-- ==========================================================
-- PEACH SUITE PRO
-- INCOME SAVE IDEMPOTENCY V1
--
-- One durable identity per appointment-income form submission.
-- Financial writes and submission completion must commit in
-- the same database transaction.
--
-- An intentional additional payment receives a NEW token.
-- Existing Income records are not modified.
-- ==========================================================

CREATE TABLE income_save_submissions (
    submission_token UUID PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    appointment_id INTEGER NOT NULL,

    request_sha256 VARCHAR(64) NOT NULL,

    income_id INTEGER,

    duplicate_override_confirmed BOOLEAN
        NOT NULL DEFAULT FALSE,

    confirmed_by_user_id INTEGER,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    completed_at TIMESTAMPTZ,

    CONSTRAINT fk_income_save_submission_workspace
        FOREIGN KEY (business_unit_id, spa_id)
        REFERENCES business_units (
            business_unit_id,
            spa_id
        ),

    CONSTRAINT chk_income_save_submission_hash
        CHECK (
            request_sha256 ~ '^[0-9a-f]{64}$'
        ),

    CONSTRAINT chk_income_save_submission_completion
        CHECK (
            (income_id IS NULL AND completed_at IS NULL)
            OR
            (income_id IS NOT NULL AND completed_at IS NOT NULL)
        )
);

CREATE INDEX idx_income_save_submissions_appointment
    ON income_save_submissions (
        spa_id,
        business_unit_id,
        appointment_id,
        created_at DESC
    );

COMMENT ON TABLE income_save_submissions IS
    'Durable appointment Income submission identities. '
    'The unique submission token prevents repeated saves, '
    'including duplicate client-credit activity. '
    'Income IDs are retained as historical references '
    'even after an Income record is deleted.';

COMMENT ON COLUMN income_save_submissions.request_sha256 IS
    'SHA-256 fingerprint of the submitted financial request '
    'for detection of token reuse with changed content.';

COMMENT ON COLUMN income_save_submissions.duplicate_override_confirmed IS
    'True only when the user explicitly confirmed an '
    'additional payment despite an existing-payment warning.';

COMMIT;
