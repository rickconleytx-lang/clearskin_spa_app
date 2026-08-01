BEGIN;


-- =========================================================
-- 1. Add workspace ownership to clients
-- =========================================================

ALTER TABLE clients
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


-- =========================================================
-- 2. Backfill existing clients
--
-- Use the spa's default active workspace. If no default is
-- marked, use the first active workspace for that spa.
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
-- 3. Fail safely if any client could not be assigned
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
-- 4. Verify each workspace belongs to the same spa
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
-- 5. Defer NOT NULL until the updated application is deployed
--
-- Production deployment order:
-- 1. Run this expand migration.
-- 2. Deploy the workspace-aware application code.
-- 3. Run clients_business_unit_v1_finalize.sql.
-- =========================================================


-- =========================================================
-- 6. Support a tenant-safe composite foreign key
-- =========================================================

CREATE UNIQUE INDEX IF NOT EXISTS
idx_business_units_business_unit_spa_unique
ON business_units (
    business_unit_id,
    spa_id
);


-- =========================================================
-- 7. Add tenant-safe foreign key
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_clients_business_unit_spa'
    ) THEN
        ALTER TABLE clients
        ADD CONSTRAINT fk_clients_business_unit_spa
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
-- 8. Workspace client indexes
-- =========================================================

CREATE INDEX IF NOT EXISTS
idx_clients_workspace_name
ON clients (
    spa_id,
    business_unit_id,
    last_name,
    first_name
);


CREATE INDEX IF NOT EXISTS
idx_clients_workspace_active
ON clients (
    spa_id,
    business_unit_id,
    active_client,
    last_name,
    first_name
);


COMMIT;
