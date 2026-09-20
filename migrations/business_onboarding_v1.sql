BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- BUSINESS ONBOARDING V1
--
-- Tracks first-time onboarding for a newly provisioned
-- Peach Suite Pro business.
--
-- Account creation, business ownership, user activation,
-- password lifecycle, MFA, and employee identity remain
-- authoritative in their respective PSP tables.
--
-- Existing businesses receive no row and are therefore not
-- placed into first-time onboarding by this migration.
-- =========================================================


CREATE TABLE IF NOT EXISTS business_onboarding (

    business_onboarding_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    account_opened_by_user_id INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    primary_onboarding_user_id INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    waiting_on_initial_activation BOOLEAN
        NOT NULL DEFAULT FALSE,

    contact_setup_completed_at TIMESTAMPTZ,

    business_setup_completed_at TIMESTAMPTZ,

    completed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT business_onboarding_spa_unique
        UNIQUE (spa_id),

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
                waiting_on_initial_activation = FALSE
                AND primary_onboarding_user_id IS NOT NULL
                AND contact_setup_completed_at IS NOT NULL
                AND business_setup_completed_at IS NOT NULL
            )
        )
);


CREATE INDEX IF NOT EXISTS
    business_onboarding_primary_user_idx
ON business_onboarding (
    primary_onboarding_user_id
)
WHERE primary_onboarding_user_id IS NOT NULL;


CREATE INDEX IF NOT EXISTS
    business_onboarding_incomplete_idx
ON business_onboarding (
    spa_id,
    waiting_on_initial_activation
)
WHERE completed_at IS NULL;


COMMENT ON TABLE business_onboarding IS
    'First-time Peach Suite Pro onboarding lifecycle for a newly '
    'provisioned business. Business ownership and individual account '
    'activation remain authoritative outside this table.';


COMMENT ON COLUMN
    business_onboarding.account_opened_by_user_id IS
    'PSP user who initiated creation of the business when known. '
    'May be a Master Admin, Owner, authorized representative, or NULL '
    'for automated provisioning. This field does not establish '
    'business ownership.';


COMMENT ON COLUMN
    business_onboarding.primary_onboarding_user_id IS
    'PSP user currently responsible for completing the business '
    'onboarding flow. May be NULL while delegated setup is waiting '
    'for the designated user to activate their account.';


COMMENT ON COLUMN
    business_onboarding.waiting_on_initial_activation IS
    'TRUE when delegated setup is waiting for the designated initial '
    'onboarding user to activate their PSP account before onboarding '
    'can continue.';


COMMENT ON COLUMN
    business_onboarding.contact_setup_completed_at IS
    'Set after the primary onboarding user confirms the PSP login '
    'email and supplies or confirms the personal mobile number stored '
    'on the users record.';


COMMENT ON COLUMN
    business_onboarding.business_setup_completed_at IS
    'Set after required first-time business setup steps are completed.';


COMMENT ON COLUMN
    business_onboarding.completed_at IS
    'Set when Peach Suite Pro first-time business onboarding is fully '
    'complete. Password and MFA completion remain authoritative in '
    'their existing security state.';


COMMIT;
