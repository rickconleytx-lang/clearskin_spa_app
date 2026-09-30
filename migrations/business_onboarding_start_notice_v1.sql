BEGIN;

-- =========================================================
-- BUSINESS ONBOARDING START NOTICE V1
--
-- Records the first deliberate start of guided onboarding and
-- the successful delivery of the corresponding internal
-- Master Admin soft-launch notification.
--
-- These fields are operational markers only. They do not
-- replace canonical user, subscription, or onboarding state.
-- =========================================================

ALTER TABLE business_onboarding
    ADD COLUMN IF NOT EXISTS onboarding_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS onboarding_started_notice_sent_at TIMESTAMPTZ;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'business_onboarding_started_time_check'
    ) THEN
        ALTER TABLE business_onboarding
            ADD CONSTRAINT
                business_onboarding_started_time_check
            CHECK (
                onboarding_started_at IS NULL
                OR onboarding_started_at >= created_at
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'business_onboarding_notice_time_check'
    ) THEN
        ALTER TABLE business_onboarding
            ADD CONSTRAINT
                business_onboarding_notice_time_check
            CHECK (
                onboarding_started_notice_sent_at IS NULL
                OR (
                    onboarding_started_at IS NOT NULL
                    AND onboarding_started_notice_sent_at
                        >= onboarding_started_at
                )
            );
    END IF;
END
$$;


COMMENT ON COLUMN
    business_onboarding.onboarding_started_at IS
    'First deliberate start of guided Peach Suite Pro onboarding, '
    'currently recorded when the primary onboarding Owner selects '
    'Get Started from the Coach Peach welcome experience.';


COMMENT ON COLUMN
    business_onboarding.onboarding_started_notice_sent_at IS
    'Timestamp when the one-time internal Master Admin notification '
    'for onboarding start was successfully accepted by the email '
    'provider. NULL means no successful notice has been recorded.';


COMMIT;
