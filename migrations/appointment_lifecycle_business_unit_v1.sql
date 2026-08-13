BEGIN;

-- =========================================================
-- APPOINTMENT LIFECYCLE WORKSPACE OWNERSHIP — EXPAND
--
-- Tables:
--   appointments
--   appointment_wrap_up
--   appointment_history
--
-- Deployment order:
-- 1. Run this expand migration.
-- 2. Deploy workspace-aware application code.
-- 3. Run appointment_lifecycle_business_unit_v1_finalize.sql.
--
-- appointment_history intentionally does NOT receive a
-- foreign key to appointments because appointment history
-- must survive appointment deletion.
-- =========================================================


-- =========================================================
-- 1. Add nullable workspace ownership to child records
-- =========================================================

ALTER TABLE appointment_wrap_up
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;

ALTER TABLE appointment_history
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


-- =========================================================
-- 2. Backfill appointment wrap-up ownership
--
-- A wrap-up belongs to the same workspace as its appointment.
-- =========================================================

UPDATE appointment_wrap_up aw
SET business_unit_id = a.business_unit_id
FROM appointments a
WHERE aw.business_unit_id IS NULL
  AND aw.appointment_id = a.appointment_id
  AND aw.spa_id = a.spa_id
  AND a.business_unit_id IS NOT NULL;


-- =========================================================
-- 3. Backfill appointment history ownership
--
-- Preferred ownership source:
--   1. Live parent appointment
--   2. Retained client
--   3. Exactly one active workspace for the spa
--
-- The final fallback preserves historical rows whose
-- appointment and/or client have already been deleted while
-- refusing to guess when multiple active workspaces exist.
-- =========================================================

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
-- 4. Validate ownership before adding constraints
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM appointments a
        LEFT JOIN business_units bu
          ON bu.business_unit_id = a.business_unit_id
         AND bu.spa_id = a.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'appointments contains invalid spa/workspace assignments';
    END IF;


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
-- 5. Strengthen appointments workspace identity
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'uq_appointments_workspace_identity'
    ) THEN
        ALTER TABLE appointments
        ADD CONSTRAINT
            uq_appointments_workspace_identity
        UNIQUE (
            appointment_id,
            spa_id,
            business_unit_id
        );
    END IF;
END
$$;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_appointments_business_unit_spa'
    ) THEN
        ALTER TABLE appointments
        ADD CONSTRAINT
            fk_appointments_business_unit_spa
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
-- 6. Add workspace foreign keys to child tables
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_appointment_wrap_up_business_unit_spa'
    ) THEN
        ALTER TABLE appointment_wrap_up
        ADD CONSTRAINT
            fk_appointment_wrap_up_business_unit_spa
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
            'fk_appointment_history_business_unit_spa'
    ) THEN
        ALTER TABLE appointment_history
        ADD CONSTRAINT
            fk_appointment_history_business_unit_spa
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
-- 7. Enforce wrap-up ownership against parent appointment
--
-- History intentionally has no parent appointment FK because
-- deleted appointments must leave their audit history behind.
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_appointment_wrap_up_appointment_workspace'
    ) THEN
        ALTER TABLE appointment_wrap_up
        ADD CONSTRAINT
            fk_appointment_wrap_up_appointment_workspace
        FOREIGN KEY (
            appointment_id,
            spa_id,
            business_unit_id
        )
        REFERENCES appointments (
            appointment_id,
            spa_id,
            business_unit_id
        )
        ON DELETE CASCADE;
    END IF;
END
$$;


-- =========================================================
-- 8. Workspace indexes
-- =========================================================

CREATE INDEX IF NOT EXISTS
idx_appointment_wrap_up_workspace_appointment
ON appointment_wrap_up (
    spa_id,
    business_unit_id,
    appointment_id
);


CREATE INDEX IF NOT EXISTS
idx_appointment_history_workspace_appointment
ON appointment_history (
    spa_id,
    business_unit_id,
    appointment_id
);


CREATE INDEX IF NOT EXISTS
idx_appointment_history_workspace_client
ON appointment_history (
    spa_id,
    business_unit_id,
    client_id,
    created_at
);


COMMIT;
