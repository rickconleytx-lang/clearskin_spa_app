BEGIN;


-- =========================================================
-- EMAIL SEND LOG WORKSPACE OWNERSHIP — EXPAND
--
-- Deployment order:
-- 1. Run this expand migration.
-- 2. Deploy workspace-aware application code.
-- 3. Run email_send_log_business_unit_v1_finalize.sql.
--
-- Historical email logs may outlive their related client.
-- Therefore no foreign key to clients is added.
-- =========================================================


ALTER TABLE email_send_log
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


UPDATE email_send_log e
SET business_unit_id = c.business_unit_id
FROM clients c
WHERE e.business_unit_id IS NULL
  AND e.client_id = c.client_id
  AND e.spa_id = c.spa_id
  AND c.business_unit_id IS NOT NULL;


-- Orphaned historical records may be assigned only when
-- the spa has exactly one active workspace.
UPDATE email_send_log e
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = e.spa_id
      AND bu.is_active = TRUE
    HAVING COUNT(*) = 1
)
WHERE e.business_unit_id IS NULL;


DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM email_send_log
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'email_send_log contains rows without business_unit_id';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM email_send_log e
        LEFT JOIN business_units bu
          ON bu.business_unit_id = e.business_unit_id
         AND bu.spa_id = e.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'email_send_log contains invalid spa/workspace assignments';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM email_send_log e
        JOIN clients c
          ON c.client_id = e.client_id
         AND c.spa_id = e.spa_id
        WHERE c.business_unit_id <> e.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'email_send_log contains client workspace mismatches';
    END IF;
END
$$;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_email_send_log_business_unit_spa'
    ) THEN
        ALTER TABLE email_send_log
        ADD CONSTRAINT fk_email_send_log_business_unit_spa
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


CREATE INDEX IF NOT EXISTS
idx_email_send_log_workspace_sent
ON email_send_log (
    spa_id,
    business_unit_id,
    sent_at DESC,
    email_log_id DESC
);


COMMIT;
