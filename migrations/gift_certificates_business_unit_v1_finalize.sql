BEGIN;

-- =========================================================
-- Gift Certificates — Enterprise workspace ownership
-- Finalize only after workspace-aware application code is
-- deployed and tested.
-- =========================================================

UPDATE gift_certificates gc
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = gc.spa_id
      AND bu.is_active = TRUE
    HAVING COUNT(*) = 1
)
WHERE gc.business_unit_id IS NULL;

UPDATE gift_certificate_email_reminders r
SET business_unit_id = gc.business_unit_id
FROM gift_certificates gc
WHERE r.business_unit_id IS NULL
  AND r.gift_cert_id = gc.gift_cert_id
  AND r.spa_id = gc.spa_id
  AND gc.business_unit_id IS NOT NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM gift_certificates
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'gift_certificates contains rows without business_unit_id';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM gift_certificate_email_reminders
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'gift_certificate_email_reminders contains rows without business_unit_id';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM gift_certificates gc
        LEFT JOIN business_units bu
          ON bu.business_unit_id = gc.business_unit_id
         AND bu.spa_id = gc.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'gift_certificates contains invalid spa/workspace assignments';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM gift_certificate_email_reminders r
        JOIN gift_certificates gc
          ON gc.gift_cert_id = r.gift_cert_id
         AND gc.spa_id = r.spa_id
        WHERE r.business_unit_id <> gc.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'gift certificate reminder workspace mismatch';
    END IF;
END
$$;

ALTER TABLE gift_certificates
ALTER COLUMN business_unit_id SET NOT NULL;

ALTER TABLE gift_certificate_email_reminders
ALTER COLUMN business_unit_id SET NOT NULL;


-- Certificate numbers belong to the workspace, not the
-- entire platform or spa.
ALTER TABLE gift_certificates
DROP CONSTRAINT IF EXISTS
gift_certificates_certificate_number_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'uq_gift_certificates_workspace_certificate_number'
    ) THEN
        ALTER TABLE gift_certificates
        ADD CONSTRAINT
            uq_gift_certificates_workspace_certificate_number
        UNIQUE (
            spa_id,
            business_unit_id,
            certificate_number
        );
    END IF;
END
$$;

COMMIT;
