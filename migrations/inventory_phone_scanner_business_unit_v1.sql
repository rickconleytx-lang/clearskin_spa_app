BEGIN;

-- =========================================================
-- Inventory Phone Scanner — Enterprise workspace ownership
--
-- Adds business_unit_id to scanner sessions and scan events.
-- Historical rows are backfilled only when the owning spa
-- has exactly one active workspace. Never guess when a spa
-- has multiple active workspaces.
-- =========================================================


-- =========================================================
-- 1. Add nullable workspace ownership
-- =========================================================

ALTER TABLE inventory_scan_sessions
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;

ALTER TABLE inventory_scan_events
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


-- =========================================================
-- 2. Backfill scanner sessions
-- =========================================================

UPDATE inventory_scan_sessions iss
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = iss.spa_id
      AND bu.is_active = TRUE
    HAVING COUNT(*) = 1
)
WHERE iss.business_unit_id IS NULL;


-- =========================================================
-- 3. Backfill scan events from their parent session
-- =========================================================

UPDATE inventory_scan_events ise
SET business_unit_id = iss.business_unit_id
FROM inventory_scan_sessions iss
WHERE ise.business_unit_id IS NULL
  AND ise.scan_session_id = iss.scan_session_id
  AND ise.spa_id = iss.spa_id
  AND iss.business_unit_id IS NOT NULL;


-- =========================================================
-- 4. Validate workspace ownership
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM inventory_scan_sessions
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'inventory_scan_sessions contains rows without business_unit_id';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM inventory_scan_events
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'inventory_scan_events contains rows without business_unit_id';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM inventory_scan_sessions iss
        LEFT JOIN business_units bu
          ON bu.business_unit_id = iss.business_unit_id
         AND bu.spa_id = iss.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'inventory_scan_sessions contains invalid spa/workspace assignments';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM inventory_scan_events ise
        LEFT JOIN business_units bu
          ON bu.business_unit_id = ise.business_unit_id
         AND bu.spa_id = ise.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'inventory_scan_events contains invalid spa/workspace assignments';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM inventory_scan_events ise
        JOIN inventory_scan_sessions iss
          ON iss.scan_session_id = ise.scan_session_id
        WHERE ise.spa_id <> iss.spa_id
           OR ise.business_unit_id <> iss.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'inventory_scan_events contains scanner-session workspace mismatches';
    END IF;
END
$$;


-- =========================================================
-- 5. Require workspace ownership
-- =========================================================

ALTER TABLE inventory_scan_sessions
ALTER COLUMN business_unit_id SET NOT NULL;

ALTER TABLE inventory_scan_events
ALTER COLUMN business_unit_id SET NOT NULL;


-- =========================================================
-- 6. Add tenant-safe workspace foreign keys
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_inventory_scan_sessions_business_unit_spa'
    ) THEN
        ALTER TABLE inventory_scan_sessions
        ADD CONSTRAINT
            fk_inventory_scan_sessions_business_unit_spa
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


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_inventory_scan_events_business_unit_spa'
    ) THEN
        ALTER TABLE inventory_scan_events
        ADD CONSTRAINT
            fk_inventory_scan_events_business_unit_spa
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
-- 7. Enforce event/session workspace identity
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'uq_inventory_scan_sessions_workspace'
    ) THEN
        ALTER TABLE inventory_scan_sessions
        ADD CONSTRAINT
            uq_inventory_scan_sessions_workspace
        UNIQUE (
            scan_session_id,
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
            'fk_inventory_scan_events_workspace_session'
    ) THEN
        ALTER TABLE inventory_scan_events
        ADD CONSTRAINT
            fk_inventory_scan_events_workspace_session
        FOREIGN KEY (
            scan_session_id,
            spa_id,
            business_unit_id
        )
        REFERENCES inventory_scan_sessions (
            scan_session_id,
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
idx_inventory_scan_sessions_workspace_active
ON inventory_scan_sessions (
    spa_id,
    business_unit_id,
    status,
    expires_at
);

CREATE INDEX IF NOT EXISTS
idx_inventory_scan_events_workspace_pending
ON inventory_scan_events (
    spa_id,
    business_unit_id,
    scan_session_id,
    status,
    scan_event_id
);

COMMIT;
