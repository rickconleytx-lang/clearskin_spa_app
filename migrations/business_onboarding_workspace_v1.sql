BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- BUSINESS ONBOARDING WORKSPACE V1
--
-- Associates first-time business onboarding with the
-- initial business workspace created during provisioning.
--
-- Existing onboarding rows remain valid when no unambiguous
-- workspace can be identified.
-- =========================================================


ALTER TABLE business_onboarding
    ADD COLUMN IF NOT EXISTS initial_business_unit_id INTEGER;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_business_onboarding_initial_business_unit'
    ) THEN
        ALTER TABLE business_onboarding
            ADD CONSTRAINT
                fk_business_onboarding_initial_business_unit
            FOREIGN KEY (initial_business_unit_id)
            REFERENCES business_units(business_unit_id)
            ON DELETE SET NULL;
    END IF;
END
$$;


-- Safely backfill only when an onboarding business has exactly
-- one workspace. Multi-workspace businesses are intentionally
-- left NULL rather than guessing which workspace was initial.
WITH single_workspace AS (
    SELECT
        spa_id,
        MIN(business_unit_id) AS business_unit_id
    FROM business_units
    GROUP BY spa_id
    HAVING COUNT(*) = 1
)
UPDATE business_onboarding bo
SET
    initial_business_unit_id = sw.business_unit_id,
    updated_at = NOW()
FROM single_workspace sw
WHERE bo.spa_id = sw.spa_id
  AND bo.initial_business_unit_id IS NULL;


CREATE INDEX IF NOT EXISTS
    business_onboarding_initial_business_unit_idx
ON business_onboarding (
    initial_business_unit_id
)
WHERE initial_business_unit_id IS NOT NULL;


COMMENT ON COLUMN
    business_onboarding.initial_business_unit_id IS
    'Initial Peach Suite Pro workspace created for this business '
    'onboarding lifecycle. Used to scope first-time canonical setup '
    'progress without inferring the active workspace from session state.';


COMMIT;
