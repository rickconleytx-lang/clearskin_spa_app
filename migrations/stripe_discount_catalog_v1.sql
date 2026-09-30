BEGIN;

-- ============================================================
-- PEACH SUITE PRO
-- STRIPE DISCOUNT CATALOG V1
--
-- Maps PSP-approved discount policies to Stripe Coupons.
--
-- Customer-entered discount codes are validated by PSP.
-- The private Friends/Family code is NEVER stored here.
--
-- Discounts are tied to the base-plan tier and billing cadence
-- so add-ons such as SMS and 10DLC assistance remain excluded.
-- ============================================================

CREATE TABLE IF NOT EXISTS stripe_discount_catalog (
    stripe_discount_catalog_id BIGSERIAL PRIMARY KEY,

    environment VARCHAR(20)
        NOT NULL DEFAULT 'test',

    discount_key VARCHAR(30) NOT NULL,

    tier_code VARCHAR(30) NOT NULL,

    billing_interval VARCHAR(20) NOT NULL,

    stripe_coupon_id VARCHAR(255) NOT NULL,

    discount_type VARCHAR(20) NOT NULL,

    percent_off NUMERIC(5,2),

    amount_off_cents INTEGER,

    currency VARCHAR(3),

    valid_through TIMESTAMPTZ,

    is_active BOOLEAN
        NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_stripe_discount_environment
        CHECK (
            environment IN ('test', 'live')
        ),

    CONSTRAINT chk_stripe_discount_key
        CHECK (
            discount_key IN (
                'launch10',
                'friends_family'
            )
        ),

    CONSTRAINT chk_stripe_discount_interval
        CHECK (
            billing_interval IN ('month', 'year')
        ),

    CONSTRAINT chk_stripe_discount_type
        CHECK (
            discount_type IN (
                'percent',
                'amount'
            )
        ),

    CONSTRAINT chk_stripe_discount_value
        CHECK (
            (
                discount_type = 'percent'
                AND percent_off IS NOT NULL
                AND percent_off > 0
                AND percent_off <= 100
                AND amount_off_cents IS NULL
                AND currency IS NULL
            )
            OR
            (
                discount_type = 'amount'
                AND percent_off IS NULL
                AND amount_off_cents IS NOT NULL
                AND amount_off_cents > 0
                AND currency IS NOT NULL
            )
        ),

    CONSTRAINT chk_stripe_discount_currency
        CHECK (
            currency IS NULL
            OR (
                currency = LOWER(currency)
                AND CHAR_LENGTH(currency) = 3
            )
        ),

    CONSTRAINT fk_stripe_discount_tier
        FOREIGN KEY (tier_code)
        REFERENCES subscription_tiers(tier_code)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_stripe_discount_active_mapping
ON stripe_discount_catalog (
    environment,
    discount_key,
    tier_code,
    billing_interval
)
WHERE is_active = TRUE;


CREATE INDEX IF NOT EXISTS
    idx_stripe_discount_lookup
ON stripe_discount_catalog (
    environment,
    discount_key,
    tier_code,
    billing_interval,
    is_active
);


COMMIT;
