BEGIN;


-- =========================================================
-- CONSENT RECORDS WORKSPACE OWNERSHIP — EXPAND
--
-- Deployment order:
-- 1. Run this expand migration.
-- 2. Deploy workspace-aware application code.
-- 3. Run consent_records_business_unit_v1_finalize.sql.
--
-- Historical consent records are intentionally allowed to
-- survive deletion of the related client. Therefore no
-- foreign key to clients is added.
-- =========================================================


-- =========================================================
-- 1. Add nullable workspace ownership
-- =========================================================

ALTER TABLE consent_records
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


-- =========================================================
-- 2. Backfill from existing client ownership
-- =========================================================

UPDATE consent_records cr
SET business_unit_id = c.business_unit_id
FROM clients c
WHERE cr.business_unit_id IS NULL
  AND cr.client_id = c.client_id
  AND cr.spa_id = c.spa_id
  AND c.business_unit_id IS NOT NULL;


-- =========================================================
-- 3. Preserve orphaned historical consent records
--
-- If the client no longer exists, assign the record only
-- when that spa has exactly one active workspace.
-- Never guess when multiple active workspaces exist.
-- =========================================================

UPDATE consent_records cr
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = cr.spa_id
      AND bu.is_active = TRUE
    HAVING COUNT(*) = 1
)
WHERE cr.business_unit_id IS NULL;


-- =========================================================
-- 4. Validate workspace ownership
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM consent_records
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'consent_records contains rows without business_unit_id';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM consent_records cr
        LEFT JOIN business_units bu
          ON bu.business_unit_id = cr.business_unit_id
         AND bu.spa_id = cr.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'consent_records contains invalid spa/workspace assignments';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM consent_records cr
        JOIN clients c
          ON c.client_id = cr.client_id
         AND c.spa_id = cr.spa_id
        WHERE c.business_unit_id <> cr.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'consent_records contains client workspace mismatches';
    END IF;
END
$$;


-- =========================================================
-- 5. Add tenant-safe workspace foreign key
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_consent_records_business_unit_spa'
    ) THEN
        ALTER TABLE consent_records
        ADD CONSTRAINT fk_consent_records_business_unit_spa
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
-- 6. Workspace/client history index
-- =========================================================

CREATE INDEX IF NOT EXISTS
idx_consent_records_workspace_client_created
ON consent_records (
    spa_id,
    business_unit_id,
    client_id,
    created_at DESC,
    consent_record_id DESC
);


COMMIT;
