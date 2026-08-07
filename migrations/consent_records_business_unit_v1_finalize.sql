BEGIN;


-- =========================================================
-- CONSENT RECORDS WORKSPACE OWNERSHIP — FINALIZE
--
-- Run only after the workspace-aware application code has
-- been deployed and tested.
-- =========================================================


-- =========================================================
-- 1. Backfill records created during deployment window
-- =========================================================

UPDATE consent_records cr
SET business_unit_id = c.business_unit_id
FROM clients c
WHERE cr.business_unit_id IS NULL
  AND cr.client_id = c.client_id
  AND cr.spa_id = c.spa_id
  AND c.business_unit_id IS NOT NULL;


UPDATE consent_records cr
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = cr.spa_id
      AND bu.is_active = TRUE
    HAVING COUNT(*) = 1
)
WHERE cr.business_unit_id IS NULL;


-- =========================================================
-- 2. Validate required workspace ownership
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM consent_records
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'consent_records contains rows without business_unit_id';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM consent_records cr
        LEFT JOIN business_units bu
          ON bu.business_unit_id = cr.business_unit_id
         AND bu.spa_id = cr.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'consent_records contains invalid spa/workspace assignments';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM consent_records cr
        JOIN clients c
          ON c.client_id = cr.client_id
         AND c.spa_id = cr.spa_id
        WHERE c.business_unit_id <> cr.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'consent_records contains client workspace mismatches';
    END IF;
END
$$;


-- =========================================================
-- 3. Enforce required workspace ownership
-- =========================================================

ALTER TABLE consent_records
ALTER COLUMN business_unit_id SET NOT NULL;


COMMIT;
