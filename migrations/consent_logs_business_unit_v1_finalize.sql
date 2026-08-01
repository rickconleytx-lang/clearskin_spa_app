BEGIN;


-- =========================================================
-- 1. Backfill rows created during the deployment window
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
-- 2. Fail safely if any row remains unassigned
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
-- 3. Verify workspace and spa ownership match
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
-- 4. Require workspace ownership
-- =========================================================

ALTER TABLE sms_consent_log
ALTER COLUMN business_unit_id SET NOT NULL;

ALTER TABLE email_consent_log
ALTER COLUMN business_unit_id SET NOT NULL;


COMMIT;
