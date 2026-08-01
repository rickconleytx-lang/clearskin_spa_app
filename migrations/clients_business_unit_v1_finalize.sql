BEGIN;


-- =========================================================
-- 1. Backfill clients created during the deployment window
-- =========================================================

UPDATE clients c
SET business_unit_id = (
    SELECT bu.business_unit_id
    FROM business_units bu
    WHERE bu.spa_id = c.spa_id
      AND bu.is_active = TRUE
    ORDER BY
        CASE
            WHEN bu.is_default = TRUE THEN 0
            ELSE 1
        END,
        bu.business_unit_id
    LIMIT 1
)
WHERE c.business_unit_id IS NULL;


-- =========================================================
-- 2. Fail safely if any client remains unassigned
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM clients
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'One or more clients could not be assigned to a business unit.';
    END IF;
END
$$;


-- =========================================================
-- 3. Verify each workspace belongs to the same spa
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM clients c
        LEFT JOIN business_units bu
          ON bu.business_unit_id = c.business_unit_id
         AND bu.spa_id = c.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'One or more clients have an invalid spa and business-unit assignment.';
    END IF;
END
$$;


-- =========================================================
-- 4. Require workspace ownership
-- =========================================================

ALTER TABLE clients
ALTER COLUMN business_unit_id SET NOT NULL;


COMMIT;
