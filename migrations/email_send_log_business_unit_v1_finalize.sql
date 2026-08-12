BEGIN;


-- =========================================================
-- EMAIL SEND LOG WORKSPACE OWNERSHIP — FINALIZE
--
-- Run after workspace-aware application code is deployed
-- and tested.
-- =========================================================


UPDATE email_send_log e
SET business_unit_id = c.business_unit_id
FROM clients c
WHERE e.business_unit_id IS NULL
  AND e.client_id = c.client_id
  AND e.spa_id = c.spa_id
  AND c.business_unit_id IS NOT NULL;


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


ALTER TABLE email_send_log
ALTER COLUMN business_unit_id SET NOT NULL;


COMMIT;
