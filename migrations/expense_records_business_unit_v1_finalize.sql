BEGIN;

-- =========================================================
-- EXPENSE RECORDS WORKSPACE OWNERSHIP — FINALIZE
--
-- Run only after the workspace-aware application code has
-- been deployed and tested.
-- =========================================================


-- =========================================================
-- 1. Backfill rows created during the deployment window
-- =========================================================

UPDATE automatic_expenses ae
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = ae.spa_id
      AND bu.is_active = TRUE
    HAVING COUNT(*) = 1
)
WHERE ae.business_unit_id IS NULL;


UPDATE automatic_expense_occurrences aeo
SET business_unit_id = ae.business_unit_id
FROM automatic_expenses ae
WHERE aeo.business_unit_id IS NULL
  AND aeo.automatic_expense_id =
      ae.automatic_expense_id
  AND aeo.spa_id = ae.spa_id
  AND ae.business_unit_id IS NOT NULL;


UPDATE expenses e
SET business_unit_id = source.business_unit_id
FROM (
    SELECT
        aeo.expense_id,
        aeo.spa_id,
        MIN(aeo.business_unit_id) AS business_unit_id
    FROM automatic_expense_occurrences aeo
    WHERE aeo.expense_id IS NOT NULL
      AND aeo.business_unit_id IS NOT NULL
    GROUP BY
        aeo.expense_id,
        aeo.spa_id
    HAVING COUNT(
        DISTINCT aeo.business_unit_id
    ) = 1
) source
WHERE e.business_unit_id IS NULL
  AND e.expense_id = source.expense_id
  AND e.spa_id = source.spa_id;


UPDATE expenses e
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = e.spa_id
      AND bu.is_active = TRUE
    HAVING COUNT(*) = 1
)
WHERE e.business_unit_id IS NULL;


-- =========================================================
-- 2. Validate required ownership and relationships
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM expenses
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'expenses contains rows without business_unit_id';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM automatic_expenses
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'automatic_expenses contains rows without business_unit_id';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM automatic_expense_occurrences
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'automatic_expense_occurrences contains rows without business_unit_id';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM expenses e
        LEFT JOIN business_units bu
          ON bu.business_unit_id = e.business_unit_id
         AND bu.spa_id = e.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'expenses contains invalid spa/workspace assignments';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM automatic_expenses ae
        LEFT JOIN business_units bu
          ON bu.business_unit_id = ae.business_unit_id
         AND bu.spa_id = ae.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'automatic_expenses contains invalid spa/workspace assignments';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM automatic_expense_occurrences aeo
        LEFT JOIN business_units bu
          ON bu.business_unit_id = aeo.business_unit_id
         AND bu.spa_id = aeo.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'automatic_expense_occurrences contains invalid spa/workspace assignments';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM automatic_expense_occurrences aeo
        JOIN automatic_expenses ae
          ON ae.automatic_expense_id =
             aeo.automatic_expense_id
         AND ae.spa_id = aeo.spa_id
        WHERE ae.business_unit_id <>
              aeo.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'automatic expense occurrence parent workspace mismatch';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM automatic_expense_occurrences aeo
        JOIN expenses e
          ON e.expense_id = aeo.expense_id
         AND e.spa_id = aeo.spa_id
        WHERE aeo.expense_id IS NOT NULL
          AND e.business_unit_id <>
              aeo.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'automatic expense occurrence posted-expense workspace mismatch';
    END IF;
END
$$;


-- =========================================================
-- 3. Enforce required workspace ownership
-- =========================================================

ALTER TABLE expenses
ALTER COLUMN business_unit_id SET NOT NULL;

ALTER TABLE automatic_expenses
ALTER COLUMN business_unit_id SET NOT NULL;

ALTER TABLE automatic_expense_occurrences
ALTER COLUMN business_unit_id SET NOT NULL;


COMMIT;
