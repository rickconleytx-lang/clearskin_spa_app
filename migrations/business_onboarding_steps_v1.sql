BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- BUSINESS ONBOARDING STEPS V1
--
-- Stores workflow review/completion markers for the guided
-- first-time setup checklist.
--
-- Canonical business data remains authoritative in its
-- existing PSP tables. This table does not duplicate service,
-- website, booking, provider, hours, or link configuration.
-- =========================================================


CREATE TABLE IF NOT EXISTS business_onboarding_steps (
    business_onboarding_step_id SERIAL PRIMARY KEY,

    business_onboarding_id INTEGER NOT NULL
        REFERENCES business_onboarding(business_onboarding_id)
        ON DELETE CASCADE,

    step_key VARCHAR(60) NOT NULL,

    reviewed_at TIMESTAMPTZ,
    reviewed_by_user_id INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    completed_at TIMESTAMPTZ,
    completed_by_user_id INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT business_onboarding_steps_unique
        UNIQUE (
            business_onboarding_id,
            step_key
        ),

    CONSTRAINT business_onboarding_steps_key_check
        CHECK (
            step_key IN (
                'service_catalog',
                'website_services',
                'public_website_settings',
                'booking_control_center',
                'business_hours',
                'provider_hours',
                'provider_services',
                'provider_time_off',
                'website_links'
            )
        ),

    CONSTRAINT business_onboarding_steps_updated_check
        CHECK (
            updated_at >= created_at
        ),

    CONSTRAINT business_onboarding_steps_reviewed_check
        CHECK (
            reviewed_at IS NULL
            OR reviewed_at >= created_at
        ),

    CONSTRAINT business_onboarding_steps_completed_check
        CHECK (
            completed_at IS NULL
            OR completed_at >= created_at
        )
);


CREATE INDEX IF NOT EXISTS
    business_onboarding_steps_incomplete_idx
ON business_onboarding_steps (
    business_onboarding_id,
    step_key
)
WHERE completed_at IS NULL;


COMMENT ON TABLE business_onboarding_steps IS
    'Per-step review and completion markers for the Peach Suite Pro '
    'first-time business setup checklist. Canonical setup data remains '
    'authoritative in the underlying feature tables.';


COMMENT ON COLUMN business_onboarding_steps.step_key IS
    'Stable application key identifying one canonical onboarding setup '
    'step. Display names, ordering, URLs, and completion rules remain '
    'application logic.';


COMMENT ON COLUMN business_onboarding_steps.reviewed_at IS
    'Set when the onboarding user has reviewed the canonical setup page '
    'for this step, including valid steps that may contain no records.';


COMMENT ON COLUMN business_onboarding_steps.completed_at IS
    'Set when the onboarding step satisfies its required setup rule and '
    'is accepted as complete for the first-time onboarding workflow.';


COMMIT;
