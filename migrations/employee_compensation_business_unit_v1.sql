BEGIN;

-- =========================================================
-- EMPLOYEE COMPENSATION WORKSPACE OWNERSHIP — EXPAND
--
-- Prerequisite:
--   employee_access_codes_v1.sql
--
-- Deployment order:
-- 1. Run this expand migration.
-- 2. Deploy workspace-aware application code.
-- 3. Run employee_compensation_business_unit_v1_finalize.sql.
--
-- Historical compensation is assigned automatically only when
-- the employee has exactly one durable workspace membership.
-- Do not guess from spa_id alone.
-- =========================================================


-- =========================================================
-- 1. Add nullable workspace ownership
-- =========================================================

ALTER TABLE employee_compensation
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


-- =========================================================
-- 2. Backfill from durable employee/workspace membership
--
-- employee_business_unit_memberships preserves the historical
-- employee/workspace relationship even when membership later
-- becomes inactive, so do not restrict this backfill to active
-- memberships.
--
-- A row is assigned only when exactly one distinct workspace
-- membership exists for that employee inside the spa.
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
-- 3. Validate ownership before adding enforcement
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
-- 4. Enforce employee/workspace ownership
--
-- The membership table has a durable unique identity on:
--   (spa_id, business_unit_id, employee_id)
--
-- This prevents a compensation row from naming an employee
-- who does not belong to the row's workspace.
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_employee_compensation_workspace_employee'
    ) THEN
        ALTER TABLE employee_compensation
        ADD CONSTRAINT
            fk_employee_compensation_workspace_employee
        FOREIGN KEY (
            spa_id,
            business_unit_id,
            employee_id
        )
        REFERENCES employee_business_unit_memberships (
            spa_id,
            business_unit_id,
            employee_id
        )
        ON DELETE RESTRICT;
    END IF;
END
$$;


-- =========================================================
-- 5. Workspace indexes
-- =========================================================

CREATE INDEX IF NOT EXISTS
idx_employee_compensation_workspace_date
ON employee_compensation (
    spa_id,
    business_unit_id,
    compensation_date DESC,
    compensation_id DESC
);


CREATE INDEX IF NOT EXISTS
idx_employee_compensation_workspace_employee_date
ON employee_compensation (
    spa_id,
    business_unit_id,
    employee_id,
    compensation_date DESC,
    compensation_id DESC
);


COMMIT;
