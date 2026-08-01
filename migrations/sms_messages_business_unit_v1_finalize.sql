-- =========================================================
-- SMS MESSAGES WORKSPACE OWNERSHIP — FINALIZE MIGRATION
-- =========================================================


-- =========================================================
-- 1. Backfill messages created during deployment window
-- =========================================================

UPDATE sms_messages sm
SET business_unit_id = c.business_unit_id
FROM clients c
WHERE sm.business_unit_id IS NULL
  AND sm.client_id = c.client_id
  AND sm.spa_id = c.spa_id
  AND c.business_unit_id IS NOT NULL;


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
-- 2. Validate all tenant ownership
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
-- 3. Enforce required tenant ownership
-- =========================================================

ALTER TABLE sms_messages
ALTER COLUMN spa_id SET NOT NULL;

ALTER TABLE sms_messages
ALTER COLUMN business_unit_id SET NOT NULL;
