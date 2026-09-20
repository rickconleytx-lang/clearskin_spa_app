BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- BUSINESS ONBOARDING V1
--
-- Tracks first-time onboarding for a newly provisioned
-- Peach Suite Pro business and its initial administrator.
--
-- Password lifecycle remains authoritative in users.
-- MFA lifecycle remains authoritative in the MFA tables.
-- Contact values remain authoritative in users.email and
-- users.sms_phone.
--
-- Existing businesses receive no row and are therefore not
-- placed into first-time onboarding by this migration.
-- =========================================================


CREATE TABLE IF NOT EXISTS business_onboarding (

    business_onboarding_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    initial_administrator_user_id INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    contact_setup_completed_at TIMESTAMPTZ,

    business_setup_completed_at TIMESTAMPTZ,

    completed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT business_onboarding_spa_unique
        UNIQUE (spa_id),

    CONSTRAINT business_onboarding_user_unique
        UNIQUE (initial_administrator_user_id),

    CONSTRAINT business_onboarding_updated_check
        CHECK (updated_at >= created_at),

    CONSTRAINT business_onboarding_contact_time_check
        CHECK (
            contact_setup_completed_at IS NULL
            OR contact_setup_completed_at >= created_at
        ),

    CONSTRAINT business_onboarding_business_time_check
        CHECK (
            business_setup_completed_at IS NULL
            OR business_setup_completed_at >= created_at
        ),

    CONSTRAINT business_onboarding_completed_time_check
        CHECK (
            completed_at IS NULL
            OR completed_at >= created_at
        ),

    CONSTRAINT business_onboarding_completion_check
        CHECK (
            completed_at IS NULL
            OR (
                contact_setup_completed_at IS NOT NULL
                AND business_setup_completed_at IS NOT NULL
            )
        )
);


CREATE INDEX IF NOT EXISTS business_onboarding_incomplete_idx
    ON business_onboarding (
        spa_id,
        initial_administrator_user_id
    )
    WHERE completed_at IS NULL;


COMMENT ON TABLE business_onboarding IS
    'First-time Peach Suite Pro onboarding lifecycle for a newly '
    'provisioned business and its initial administrator. Existing '
    'businesses without a row are not subject to this onboarding flow.';


COMMENT ON COLUMN business_onboarding.contact_setup_completed_at IS
    'Set after the initial administrator confirms the PSP login email '
    'and supplies or confirms the personal mobile number stored on '
    'the users record.';


COMMENT ON COLUMN business_onboarding.business_setup_completed_at IS
    'Set after required first-time business setup steps are completed.';


COMMENT ON COLUMN business_onboarding.completed_at IS
    'Set when Peach Suite Pro first-time business onboarding is fully '
    'complete. Password and MFA completion are validated from their '
    'existing authoritative security state before this is set.';


COMMIT;
