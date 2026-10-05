BEGIN;

-- ==========================================================
-- PEACH SUITE PRO
-- BUSINESS BILLING + ACCESS MODEL V1
--
-- Keep these concerns separate:
--
--   subscription_tier_id = PSP feature plan / entitlements
--   billing_mode         = standard or complimentary
--   subscription_status  = subscription lifecycle state
--   access_status        = active, grace, or restricted
--
-- Stripe billing state remains authoritative in the Stripe
-- billing tables for businesses that have a Stripe subscription.
-- ==========================================================


-- ==========================================================
-- 1. BILLING MODE
-- ==========================================================

ALTER TABLE spas
    ADD COLUMN IF NOT EXISTS billing_mode VARCHAR(30);

UPDATE spas
SET billing_mode = CASE
    WHEN LOWER(TRIM(COALESCE(subscription_status, ''))) = 'complimentary'
        THEN 'complimentary'
    ELSE 'standard'
END
WHERE billing_mode IS NULL;

ALTER TABLE spas
    ALTER COLUMN billing_mode SET DEFAULT 'standard';

ALTER TABLE spas
    ALTER COLUMN billing_mode SET NOT NULL;

ALTER TABLE spas
    DROP CONSTRAINT IF EXISTS chk_spas_billing_mode;

ALTER TABLE spas
    ADD CONSTRAINT chk_spas_billing_mode
    CHECK (
        billing_mode IN (
            'standard',
            'complimentary'
        )
    );


-- ==========================================================
-- 2. PSP ACCESS STATUS
-- ==========================================================

ALTER TABLE spas
    ADD COLUMN IF NOT EXISTS access_status VARCHAR(30);

UPDATE spas
SET access_status = CASE
    WHEN active = TRUE
        THEN 'active'
    ELSE 'restricted'
END
WHERE access_status IS NULL;

ALTER TABLE spas
    ALTER COLUMN access_status SET DEFAULT 'active';

ALTER TABLE spas
    ALTER COLUMN access_status SET NOT NULL;

ALTER TABLE spas
    DROP CONSTRAINT IF EXISTS chk_spas_access_status;

ALTER TABLE spas
    ADD CONSTRAINT chk_spas_access_status
    CHECK (
        access_status IN (
            'active',
            'grace',
            'restricted'
        )
    );


-- ==========================================================
-- 3. COMPLIMENTARY BILLING METADATA
-- ==========================================================

ALTER TABLE spas
    ADD COLUMN IF NOT EXISTS complimentary_started_at TIMESTAMPTZ;

ALTER TABLE spas
    ADD COLUMN IF NOT EXISTS complimentary_ends_at TIMESTAMPTZ;

ALTER TABLE spas
    ADD COLUMN IF NOT EXISTS complimentary_reason TEXT;

ALTER TABLE spas
    ADD COLUMN IF NOT EXISTS complimentary_set_by INTEGER;

ALTER TABLE spas
    ADD COLUMN IF NOT EXISTS complimentary_set_at TIMESTAMPTZ;


-- Preserve historical Complimentary accounts, if any existed
-- before billing_mode was introduced.

UPDATE spas
SET
    complimentary_started_at = COALESCE(
        complimentary_started_at,
        CURRENT_TIMESTAMP
    ),
    complimentary_set_at = COALESCE(
        complimentary_set_at,
        CURRENT_TIMESTAMP
    )
WHERE billing_mode = 'complimentary';


-- ==========================================================
-- 4. INTEGRITY RULES
-- ==========================================================

ALTER TABLE spas
    DROP CONSTRAINT IF EXISTS chk_spas_complimentary_dates;

ALTER TABLE spas
    ADD CONSTRAINT chk_spas_complimentary_dates
    CHECK (
        complimentary_ends_at IS NULL
        OR complimentary_started_at IS NULL
        OR complimentary_ends_at > complimentary_started_at
    );


-- complimentary_set_by records the PSP user who granted or
-- most recently updated complimentary billing.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_spas_complimentary_set_by'
    ) THEN
        ALTER TABLE spas
            ADD CONSTRAINT fk_spas_complimentary_set_by
            FOREIGN KEY (complimentary_set_by)
            REFERENCES users(user_id)
            ON DELETE SET NULL;
    END IF;
END $$;


-- ==========================================================
-- 5. DOCUMENTATION
-- ==========================================================

COMMENT ON COLUMN spas.billing_mode IS
    'PSP billing treatment: standard or complimentary. '
    'Independent from subscription tier and Stripe lifecycle state.';

COMMENT ON COLUMN spas.access_status IS
    'PSP operational access state: active, grace, or restricted.';

COMMENT ON COLUMN spas.complimentary_started_at IS
    'When complimentary billing became effective.';

COMMENT ON COLUMN spas.complimentary_ends_at IS
    'Optional date/time when complimentary billing ends.';

COMMENT ON COLUMN spas.complimentary_reason IS
    'Master Admin reason for granting complimentary billing.';

COMMENT ON COLUMN spas.complimentary_set_by IS
    'PSP user_id that most recently granted or updated complimentary billing.';

COMMENT ON COLUMN spas.complimentary_set_at IS
    'When complimentary billing was most recently granted or updated.';


COMMIT;
