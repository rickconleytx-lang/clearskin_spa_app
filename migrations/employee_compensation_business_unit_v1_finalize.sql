BEGIN;

-- =========================================================
-- EMPLOYEE COMPENSATION WORKSPACE OWNERSHIP — FINALIZE
--
-- Prerequisite:
--   employee_compensation_business_unit_v1.sql
--
-- Run only after workspace-aware employee compensation
-- application code has been deployed and tested.
-- =========================================================


-- =========================================================
-- 1. Backfill rows created during the deployment window
--
-- Assign only when exactly one durable employee/workspace
-- membership exists. Never guess from spa_id alone.
-- =========================================================

UPDATE employee_compensation ec
SET business_unit_id = source.business_unit_id
FROM (
    SELECT
        ec_source.compensation_id,
        ec_source.spa_id,
        MIN(ebum.business_unit_id) AS business_unit_id
    FROM employee_compensation ec_source
    JOIN employee_business_unit_memberships ebum
      ON ebum.spa_id = ec_source.spa_id
     AND ebum.employee_id = ec_source.employee_id
    WHERE ec_source.business_unit_id IS NULL
    GROUP BY
        ec_source.compensation_id,
        ec_source.spa_id
    HAVING COUNT(
        DISTINCT ebum.business_unit_id
    ) = 1
) source
WHERE ec.business_unit_id IS NULL
  AND ec.compensation_id = source.compensation_id
  AND ec.spa_id = source.spa_id;


-- =========================================================
-- 2. Validate required ownership and relationship
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM employee_compensation
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'employee_compensation contains rows without unambiguous workspace ownership';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM employee_compensation ec
        LEFT JOIN employee_business_unit_memberships ebum
          ON ebum.spa_id = ec.spa_id
         AND ebum.business_unit_id = ec.business_unit_id
         AND ebum.employee_id = ec.employee_id
        WHERE ebum.employee_business_unit_membership_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'employee_compensation contains invalid employee/workspace assignments';
    END IF;
END
$$;


-- =========================================================
-- 3. Enforce required workspace ownership
-- =========================================================

ALTER TABLE employee_compensation
ALTER COLUMN business_unit_id SET NOT NULL;


COMMIT;
