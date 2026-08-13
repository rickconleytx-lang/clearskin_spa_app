BEGIN;

-- =========================================================
-- APPOINTMENT LIFECYCLE WORKSPACE OWNERSHIP — FINALIZE
--
-- Run only after the workspace-aware application code has
-- been deployed and tested.
-- =========================================================


-- =========================================================
-- 1. Backfill rows created during the deployment window
-- =========================================================

UPDATE appointment_wrap_up aw
SET business_unit_id = a.business_unit_id
FROM appointments a
WHERE aw.business_unit_id IS NULL
  AND aw.appointment_id = a.appointment_id
  AND aw.spa_id = a.spa_id
  AND a.business_unit_id IS NOT NULL;


UPDATE appointment_history ah
SET business_unit_id = a.business_unit_id
FROM appointments a
WHERE ah.business_unit_id IS NULL
  AND ah.appointment_id = a.appointment_id
  AND ah.spa_id = a.spa_id
  AND a.business_unit_id IS NOT NULL;


UPDATE appointment_history ah
SET business_unit_id = c.business_unit_id
FROM clients c
WHERE ah.business_unit_id IS NULL
  AND ah.client_id IS NOT NULL
  AND ah.client_id = c.client_id
  AND ah.spa_id = c.spa_id
  AND c.business_unit_id IS NOT NULL;


UPDATE appointment_history ah
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = ah.spa_id
      AND bu.is_active = TRUE
    HAVING COUNT(*) = 1
)
WHERE ah.business_unit_id IS NULL;


-- =========================================================
-- 2. Validate required ownership and relationships
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM appointment_wrap_up
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'appointment_wrap_up contains rows without business_unit_id';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM appointment_history
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'appointment_history contains rows without business_unit_id';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM appointment_wrap_up aw
        LEFT JOIN business_units bu
          ON bu.business_unit_id = aw.business_unit_id
         AND bu.spa_id = aw.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'appointment_wrap_up contains invalid spa/workspace assignments';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM appointment_history ah
        LEFT JOIN business_units bu
          ON bu.business_unit_id = ah.business_unit_id
         AND bu.spa_id = ah.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'appointment_history contains invalid spa/workspace assignments';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM appointment_wrap_up aw
        JOIN appointments a
          ON a.appointment_id = aw.appointment_id
         AND a.spa_id = aw.spa_id
        WHERE a.business_unit_id <> aw.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'appointment_wrap_up parent workspace mismatch';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM appointment_history ah
        JOIN appointments a
          ON a.appointment_id = ah.appointment_id
         AND a.spa_id = ah.spa_id
        WHERE a.business_unit_id <> ah.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'appointment_history live-parent workspace mismatch';
    END IF;
END
$$;


-- =========================================================
-- 3. Require workspace ownership
-- =========================================================

ALTER TABLE appointment_wrap_up
ALTER COLUMN business_unit_id SET NOT NULL;

ALTER TABLE appointment_history
ALTER COLUMN business_unit_id SET NOT NULL;


COMMIT;
