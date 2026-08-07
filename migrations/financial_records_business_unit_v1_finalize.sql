BEGIN;


-- =========================================================
-- FINANCIAL RECORDS WORKSPACE OWNERSHIP — FINALIZE
--
-- Run only after the workspace-aware application code has
-- been deployed and tested.
-- =========================================================


-- =========================================================
-- 1. Backfill income created during deployment window
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
-- 2. Backfill credit transactions created during window
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
-- 3. Backfill referrals created during deployment window
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
-- 4. Validate required workspace ownership
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
-- 5. Enforce required workspace ownership
-- =========================================================

ALTER TABLE income
ALTER COLUMN business_unit_id SET NOT NULL;

ALTER TABLE client_credit_transactions
ALTER COLUMN business_unit_id SET NOT NULL;

ALTER TABLE referrals
ALTER COLUMN business_unit_id SET NOT NULL;


COMMIT;
