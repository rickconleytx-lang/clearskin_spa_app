BEGIN;

-- =========================================================
-- Gift Certificates — Enterprise workspace ownership
--
-- Expand migration:
--   1. Add nullable business_unit_id columns.
--   2. Backfill only when ownership is deterministic.
--   3. Add tenant-safe foreign keys and indexes.
--
-- Do NOT make the columns NOT NULL or remove the legacy
-- global certificate-number uniqueness until the workspace-
-- aware application code is deployed and tested.
-- =========================================================

ALTER TABLE gift_certificates
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;

ALTER TABLE gift_certificate_email_reminders
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


-- Historical certificates may be assigned only when the
-- spa has exactly one active workspace.
UPDATE gift_certificates gc
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = gc.spa_id
      AND bu.is_active = TRUE
    HAVING COUNT(*) = 1
)
WHERE gc.business_unit_id IS NULL;


-- Reminder history inherits ownership from its certificate.
UPDATE gift_certificate_email_reminders r
SET business_unit_id = gc.business_unit_id
FROM gift_certificates gc
WHERE r.business_unit_id IS NULL
  AND r.gift_cert_id = gc.gift_cert_id
  AND r.spa_id = gc.spa_id
  AND gc.business_unit_id IS NOT NULL;


-- Validate deterministic ownership before adding constraints.
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


-- Tenant-safe workspace foreign keys.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_gift_certificates_business_unit_spa'
    ) THEN
        ALTER TABLE gift_certificates
        ADD CONSTRAINT
            fk_gift_certificates_business_unit_spa
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
            'fk_gift_certificate_reminders_business_unit_spa'
    ) THEN
        ALTER TABLE gift_certificate_email_reminders
        ADD CONSTRAINT
            fk_gift_certificate_reminders_business_unit_spa
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


-- Composite parent identity for child ownership enforcement.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'uq_gift_certificates_workspace_identity'
    ) THEN
        ALTER TABLE gift_certificates
        ADD CONSTRAINT
            uq_gift_certificates_workspace_identity
        UNIQUE (
            gift_cert_id,
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
            'fk_gift_certificate_reminders_workspace_certificate'
    ) THEN
        ALTER TABLE gift_certificate_email_reminders
        ADD CONSTRAINT
            fk_gift_certificate_reminders_workspace_certificate
        FOREIGN KEY (
            gift_cert_id,
            spa_id,
            business_unit_id
        )
        REFERENCES gift_certificates (
            gift_cert_id,
            spa_id,
            business_unit_id
        )
        ON DELETE CASCADE;
    END IF;
END
$$;


CREATE INDEX IF NOT EXISTS
idx_gift_certificates_workspace_date
ON gift_certificates (
    spa_id,
    business_unit_id,
    date_issued DESC,
    gift_cert_id DESC
);

CREATE INDEX IF NOT EXISTS
idx_gift_certificate_reminders_workspace_sent
ON gift_certificate_email_reminders (
    spa_id,
    business_unit_id,
    gift_cert_id,
    sent_date DESC,
    gc_email_reminder_id DESC
);

COMMIT;
