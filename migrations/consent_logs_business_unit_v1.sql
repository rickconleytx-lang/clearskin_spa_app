BEGIN;


-- =========================================================
-- 1. Add workspace ownership to consent logs
-- =========================================================

ALTER TABLE sms_consent_log
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;

ALTER TABLE email_consent_log
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


-- =========================================================
-- 2. Backfill from the linked client when available
-- =========================================================

UPDATE sms_consent_log l
SET business_unit_id = c.business_unit_id
FROM clients c
WHERE c.client_id = l.client_id
  AND c.spa_id = l.spa_id
  AND l.business_unit_id IS NULL;


UPDATE email_consent_log l
SET business_unit_id = c.business_unit_id
FROM clients c
WHERE c.client_id = l.client_id
  AND c.spa_id = l.spa_id
  AND l.business_unit_id IS NULL;


-- =========================================================
-- 3. Backfill unresolved historical rows
--
-- Deleted or missing clients cannot provide workspace
-- ownership. Use the spa's default active workspace, or the
-- first active workspace if no default is marked.
-- =========================================================

UPDATE sms_consent_log l
SET business_unit_id = (
    SELECT bu.business_unit_id
    FROM business_units bu
    WHERE bu.spa_id = l.spa_id
      AND bu.is_active = TRUE
    ORDER BY
        CASE
            WHEN bu.is_default = TRUE THEN 0
            ELSE 1
        END,
        bu.business_unit_id
    LIMIT 1
)
WHERE l.business_unit_id IS NULL;


UPDATE email_consent_log l
SET business_unit_id = (
    SELECT bu.business_unit_id
    FROM business_units bu
    WHERE bu.spa_id = l.spa_id
      AND bu.is_active = TRUE
    ORDER BY
        CASE
            WHEN bu.is_default = TRUE THEN 0
            ELSE 1
        END,
        bu.business_unit_id
    LIMIT 1
)
WHERE l.business_unit_id IS NULL;


-- =========================================================
-- 4. Fail safely if any consent log remains unassigned
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM sms_consent_log
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'One or more SMS consent logs could not be assigned to a business unit.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM email_consent_log
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'One or more email consent logs could not be assigned to a business unit.';
    END IF;
END
$$;


-- =========================================================
-- 5. Verify workspace and spa ownership match
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM sms_consent_log l
        LEFT JOIN business_units bu
          ON bu.business_unit_id = l.business_unit_id
         AND bu.spa_id = l.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'One or more SMS consent logs have an invalid spa and business-unit assignment.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM email_consent_log l
        LEFT JOIN business_units bu
          ON bu.business_unit_id = l.business_unit_id
         AND bu.spa_id = l.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'One or more email consent logs have an invalid spa and business-unit assignment.';
    END IF;
END
$$;


-- =========================================================
-- 6. Add tenant-safe foreign keys
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_sms_consent_log_business_unit_spa'
    ) THEN
        ALTER TABLE sms_consent_log
        ADD CONSTRAINT fk_sms_consent_log_business_unit_spa
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
        WHERE conname = 'fk_email_consent_log_business_unit_spa'
    ) THEN
        ALTER TABLE email_consent_log
        ADD CONSTRAINT fk_email_consent_log_business_unit_spa
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
-- 7. Workspace consent-history indexes
-- =========================================================

CREATE INDEX IF NOT EXISTS
idx_sms_consent_log_workspace_client_created
ON sms_consent_log (
    spa_id,
    business_unit_id,
    client_id,
    created_at DESC
);


CREATE INDEX IF NOT EXISTS
idx_email_consent_log_workspace_client_created
ON email_consent_log (
    spa_id,
    business_unit_id,
    client_id,
    created_at DESC
);


-- =========================================================
-- 8. Defer NOT NULL until application deployment
--
-- Deployment order:
-- 1. Run this expand migration.
-- 2. Deploy the workspace-aware application code.
-- 3. Run consent_logs_business_unit_v1_finalize.sql.
-- =========================================================


COMMIT;
