BEGIN;

-- =========================================================
-- EXPENSE RECORDS WORKSPACE OWNERSHIP — EXPAND
--
-- Tables:
--   expenses
--   automatic_expenses
--   automatic_expense_occurrences
--
-- Deployment order:
-- 1. Run this expand migration.
-- 2. Deploy workspace-aware application code.
-- 3. Run expense_records_business_unit_v1_finalize.sql.
-- =========================================================


-- =========================================================
-- 1. Add nullable workspace ownership
-- =========================================================

ALTER TABLE expenses
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;

ALTER TABLE automatic_expenses
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;

ALTER TABLE automatic_expense_occurrences
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


-- =========================================================
-- 2. Backfill recurring expense definitions
--
-- Historical recurring expenses may be assigned
-- automatically only when the spa has exactly one active
-- workspace.
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


-- =========================================================
-- 3. Backfill recurring expense occurrences
--
-- An occurrence belongs to the same workspace as its parent
-- recurring expense.
-- =========================================================

UPDATE automatic_expense_occurrences aeo
SET business_unit_id = ae.business_unit_id
FROM automatic_expenses ae
WHERE aeo.business_unit_id IS NULL
  AND aeo.automatic_expense_id =
      ae.automatic_expense_id
  AND aeo.spa_id = ae.spa_id
  AND ae.business_unit_id IS NOT NULL;


-- =========================================================
-- 4. Backfill posted expenses
--
-- Prefer ownership from an automatic-expense occurrence when
-- one exists. Remaining standalone expenses may be assigned
-- automatically only when the spa has exactly one active
-- workspace.
-- =========================================================

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
-- 5. Validate ownership
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
-- 6. Workspace foreign keys
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_expenses_business_unit_spa'
    ) THEN
        ALTER TABLE expenses
        ADD CONSTRAINT
            fk_expenses_business_unit_spa
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        );
    END IF;


    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_automatic_expenses_business_unit_spa'
    ) THEN
        ALTER TABLE automatic_expenses
        ADD CONSTRAINT
            fk_automatic_expenses_business_unit_spa
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        );
    END IF;


    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_automatic_expense_occurrences_business_unit_spa'
    ) THEN
        ALTER TABLE automatic_expense_occurrences
        ADD CONSTRAINT
            fk_automatic_expense_occurrences_business_unit_spa
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        );
    END IF;
END
$$;


-- =========================================================
-- 7. Composite identities for child ownership enforcement
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'uq_expenses_workspace_identity'
    ) THEN
        ALTER TABLE expenses
        ADD CONSTRAINT
            uq_expenses_workspace_identity
        UNIQUE (
            expense_id,
            spa_id,
            business_unit_id
        );
    END IF;


    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'uq_automatic_expenses_workspace_identity'
    ) THEN
        ALTER TABLE automatic_expenses
        ADD CONSTRAINT
            uq_automatic_expenses_workspace_identity
        UNIQUE (
            automatic_expense_id,
            spa_id,
            business_unit_id
        );
    END IF;
END
$$;


-- =========================================================
-- 8. Child-to-parent workspace enforcement
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_automatic_expense_occurrences_workspace_parent'
    ) THEN
        ALTER TABLE automatic_expense_occurrences
        ADD CONSTRAINT
            fk_automatic_expense_occurrences_workspace_parent
        FOREIGN KEY (
            automatic_expense_id,
            spa_id,
            business_unit_id
        )
        REFERENCES automatic_expenses (
            automatic_expense_id,
            spa_id,
            business_unit_id
        )
        ON DELETE CASCADE;
    END IF;


    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_automatic_expense_occurrences_workspace_expense'
    ) THEN
        ALTER TABLE automatic_expense_occurrences
        ADD CONSTRAINT
            fk_automatic_expense_occurrences_workspace_expense
        FOREIGN KEY (
            expense_id,
            spa_id,
            business_unit_id
        )
        REFERENCES expenses (
            expense_id,
            spa_id,
            business_unit_id
        );
    END IF;
END
$$;


-- =========================================================
-- 9. Workspace indexes
-- =========================================================

CREATE INDEX IF NOT EXISTS
idx_expenses_workspace_date
ON expenses (
    spa_id,
    business_unit_id,
    expense_date DESC,
    expense_id DESC
);


CREATE INDEX IF NOT EXISTS
idx_automatic_expenses_workspace_next_post
ON automatic_expenses (
    spa_id,
    business_unit_id,
    is_active,
    next_post_date,
    automatic_expense_id
);


CREATE INDEX IF NOT EXISTS
idx_automatic_expense_occurrences_workspace_processed
ON automatic_expense_occurrences (
    spa_id,
    business_unit_id,
    automatic_expense_id,
    processed_at DESC,
    occurrence_id DESC
);


COMMIT;
