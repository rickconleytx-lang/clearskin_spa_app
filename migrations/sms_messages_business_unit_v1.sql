-- =========================================================
-- SMS MESSAGES WORKSPACE OWNERSHIP — EXPAND MIGRATION
-- =========================================================


-- =========================================================
-- 1. Add nullable workspace column
-- =========================================================

ALTER TABLE sms_messages
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


-- =========================================================
-- 2. Backfill from the linked client
-- =========================================================

UPDATE sms_messages sm
SET business_unit_id = c.business_unit_id
FROM clients c
WHERE sm.business_unit_id IS NULL
  AND sm.client_id = c.client_id
  AND sm.spa_id = c.spa_id
  AND c.business_unit_id IS NOT NULL;


-- =========================================================
-- 3. Backfill historical or unmatched messages
--
-- Prefer the spa's active default workspace. If no active
-- default exists, use the first active workspace.
-- =========================================================

UPDATE sms_messages sm
SET business_unit_id = (
    SELECT bu.business_unit_id
    FROM business_units bu
    WHERE bu.spa_id = sm.spa_id
      AND bu.is_active = TRUE
    ORDER BY
        bu.is_default DESC,
        bu.business_unit_id ASC
    LIMIT 1
)
WHERE sm.business_unit_id IS NULL
  AND sm.spa_id IS NOT NULL;


-- =========================================================
-- 4. Validate backfill
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM sms_messages
        WHERE spa_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'sms_messages contains rows without spa_id';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM sms_messages
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'sms_messages contains rows without business_unit_id';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM sms_messages sm
        LEFT JOIN business_units bu
          ON bu.business_unit_id = sm.business_unit_id
         AND bu.spa_id = sm.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'sms_messages contains invalid spa/workspace assignments';
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
        WHERE conname = 'fk_sms_messages_business_unit_spa'
    ) THEN
        ALTER TABLE sms_messages
        ADD CONSTRAINT fk_sms_messages_business_unit_spa
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
-- 6. Add workspace history index
-- =========================================================

CREATE INDEX IF NOT EXISTS
    idx_sms_messages_workspace_client_created
ON sms_messages (
    spa_id,
    business_unit_id,
    client_id,
    created_at DESC
);
