BEGIN;


-- =========================================================
-- 1. Add workspace ownership to appointments
-- =========================================================

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


-- =========================================================
-- 2. Backfill existing appointments
--
-- Use the spa's default active workspace. If no default is
-- marked, use the first active workspace for that spa.
-- =========================================================

UPDATE appointments a
SET business_unit_id = (
    SELECT bu.business_unit_id
    FROM business_units bu
    WHERE bu.spa_id = a.spa_id
      AND bu.is_active = TRUE
    ORDER BY
        CASE
            WHEN bu.is_default = TRUE THEN 0
            ELSE 1
        END,
        bu.business_unit_id
    LIMIT 1
)
WHERE a.business_unit_id IS NULL;


-- =========================================================
-- 3. Fail safely if any appointment could not be assigned
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM appointments
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'One or more appointments could not be assigned to a business unit.';
    END IF;
END
$$;


-- =========================================================
-- 4. Require workspace ownership
-- =========================================================

ALTER TABLE appointments
ALTER COLUMN business_unit_id SET NOT NULL;


-- =========================================================
-- 5. Add foreign key safely
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_appointments_business_unit'
    ) THEN
        ALTER TABLE appointments
        ADD CONSTRAINT fk_appointments_business_unit
        FOREIGN KEY (business_unit_id)
        REFERENCES business_units (business_unit_id);
    END IF;
END
$$;


-- =========================================================
-- 6. Availability-engine indexes
-- =========================================================

CREATE INDEX IF NOT EXISTS
idx_appointments_workspace_date_time
ON appointments (
    spa_id,
    business_unit_id,
    appointment_date,
    appointment_time
);


CREATE INDEX IF NOT EXISTS
idx_appointments_workspace_provider_date
ON appointments (
    spa_id,
    business_unit_id,
    provider_employee_id,
    appointment_date,
    appointment_time
);


COMMIT;
