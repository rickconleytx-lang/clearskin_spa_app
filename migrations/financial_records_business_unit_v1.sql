BEGIN;


-- =========================================================
-- FINANCIAL RECORDS WORKSPACE OWNERSHIP — EXPAND
--
-- Tables:
--   income
--   client_credit_transactions
--   referrals
--
-- Deployment order:
-- 1. Run this expand migration.
-- 2. Deploy workspace-aware application code.
-- 3. Run financial_records_business_unit_v1_finalize.sql.
-- =========================================================


-- =========================================================
-- 1. Add nullable workspace ownership
-- =========================================================

ALTER TABLE income
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;

ALTER TABLE client_credit_transactions
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;

ALTER TABLE referrals
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


-- =========================================================
-- 2. Backfill income
--
-- Prefer the linked appointment, then the linked client.
-- Unlinked income may be assigned automatically only when
-- the spa has exactly one active workspace.
-- =========================================================

UPDATE income i
SET business_unit_id = a.business_unit_id
FROM appointments a
WHERE i.business_unit_id IS NULL
  AND i.appointment_id = a.appointment_id
  AND i.spa_id = a.spa_id
  AND a.business_unit_id IS NOT NULL;


UPDATE income i
SET business_unit_id = c.business_unit_id
FROM clients c
WHERE i.business_unit_id IS NULL
  AND i.client_id = c.client_id
  AND i.spa_id = c.spa_id
  AND c.business_unit_id IS NOT NULL;


UPDATE income i
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = i.spa_id
      AND bu.is_active = TRUE
    HAVING COUNT(*) = 1
)
WHERE i.business_unit_id IS NULL;


-- =========================================================
-- 3. Backfill client credit transactions
--
-- Prefer the linked client's workspace. An unmatched
-- transaction may be assigned automatically only when the
-- spa has exactly one active workspace.
-- =========================================================

UPDATE client_credit_transactions t
SET business_unit_id = c.business_unit_id
FROM clients c
WHERE t.business_unit_id IS NULL
  AND t.client_id = c.client_id
  AND t.spa_id = c.spa_id
  AND c.business_unit_id IS NOT NULL;


UPDATE client_credit_transactions t
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = t.spa_id
      AND bu.is_active = TRUE
    HAVING COUNT(*) = 1
)
WHERE t.business_unit_id IS NULL;


-- =========================================================
-- 4. Backfill referrals
--
-- A referral belongs to the referred client's workspace.
-- =========================================================

UPDATE referrals r
SET business_unit_id = c.business_unit_id
FROM clients c
WHERE r.business_unit_id IS NULL
  AND r.referred_client_id = c.client_id
  AND r.spa_id = c.spa_id
  AND c.business_unit_id IS NOT NULL;


UPDATE referrals r
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = r.spa_id
      AND bu.is_active = TRUE
    HAVING COUNT(*) = 1
)
WHERE r.business_unit_id IS NULL;


-- =========================================================
-- 5. Validate all backfills and linked ownership
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM income
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'income contains rows without business_unit_id';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM client_credit_transactions
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'client_credit_transactions contains rows without business_unit_id';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM referrals
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'referrals contains rows without business_unit_id';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM income i
        LEFT JOIN business_units bu
          ON bu.business_unit_id = i.business_unit_id
         AND bu.spa_id = i.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'income contains invalid spa/workspace assignments';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM client_credit_transactions t
        LEFT JOIN business_units bu
          ON bu.business_unit_id = t.business_unit_id
         AND bu.spa_id = t.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'client_credit_transactions contains invalid spa/workspace assignments';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM referrals r
        LEFT JOIN business_units bu
          ON bu.business_unit_id = r.business_unit_id
         AND bu.spa_id = r.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'referrals contains invalid spa/workspace assignments';
    END IF;


    IF EXISTS (
        SELECT 1
        FROM income i
        JOIN appointments a
          ON a.appointment_id = i.appointment_id
         AND a.spa_id = i.spa_id
        WHERE a.business_unit_id <> i.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'income contains appointment workspace mismatches';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM income i
        JOIN clients c
          ON c.client_id = i.client_id
         AND c.spa_id = i.spa_id
        WHERE c.business_unit_id <> i.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'income contains client workspace mismatches';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM client_credit_transactions t
        JOIN clients c
          ON c.client_id = t.client_id
         AND c.spa_id = t.spa_id
        WHERE c.business_unit_id <> t.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'client_credit_transactions contains client workspace mismatches';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM referrals r
        JOIN clients c
          ON c.client_id = r.referred_client_id
         AND c.spa_id = r.spa_id
        WHERE c.business_unit_id <> r.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'referrals contains referred-client workspace mismatches';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM referrals r
        JOIN clients c
          ON c.client_id = r.referrer_client_id
         AND c.spa_id = r.spa_id
        WHERE r.referrer_client_id IS NOT NULL
          AND c.business_unit_id <> r.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'referrals contains cross-workspace client referrals';
    END IF;
END
$$;


-- =========================================================
-- 6. Add tenant-safe composite foreign keys
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_income_business_unit_spa'
    ) THEN
        ALTER TABLE income
        ADD CONSTRAINT fk_income_business_unit_spa
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        );
    END IF;


    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_client_credit_transactions_business_unit_spa'
    ) THEN
        ALTER TABLE client_credit_transactions
        ADD CONSTRAINT
            fk_client_credit_transactions_business_unit_spa
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        );
    END IF;


    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_referrals_business_unit_spa'
    ) THEN
        ALTER TABLE referrals
        ADD CONSTRAINT fk_referrals_business_unit_spa
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
-- 7. Workspace indexes
-- =========================================================

CREATE INDEX IF NOT EXISTS
idx_income_workspace_date
ON income (
    spa_id,
    business_unit_id,
    income_date DESC,
    income_id DESC
);


CREATE INDEX IF NOT EXISTS
idx_client_credit_workspace_client_date
ON client_credit_transactions (
    spa_id,
    business_unit_id,
    client_id,
    transaction_date DESC,
    credit_transaction_id DESC
);


CREATE INDEX IF NOT EXISTS
idx_referrals_workspace_referred_client
ON referrals (
    spa_id,
    business_unit_id,
    referred_client_id,
    referral_id DESC
);


CREATE INDEX IF NOT EXISTS
idx_referrals_workspace_referrer_client
ON referrals (
    spa_id,
    business_unit_id,
    referrer_client_id
)
WHERE referrer_client_id IS NOT NULL;


COMMIT;
