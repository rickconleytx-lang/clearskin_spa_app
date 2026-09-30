BEGIN;

-- ============================================================
-- PEACH SUITE PRO
-- STRIPE PRICE CATALOG V1
--
-- Maps PSP commercial plans/add-ons to environment-specific
-- Stripe Products and Prices.
--
-- This table is intentionally separate from subscription_tiers:
--   subscription_tiers = PSP feature/entitlement identity
--   stripe_price_catalog = Stripe billing/pricing identity
--
-- Enterprise remains Contact Us and requires no catalog row.
-- ============================================================

CREATE TABLE IF NOT EXISTS stripe_price_catalog (
    stripe_price_catalog_id BIGSERIAL PRIMARY KEY,

    environment VARCHAR(20)
        NOT NULL DEFAULT 'test',

    item_kind VARCHAR(30) NOT NULL,

    -- Required only for base-plan prices.
    -- Add-ons are platform-wide and therefore have no tier_code.
    tier_code VARCHAR(30),

    billing_interval VARCHAR(20) NOT NULL,

    stripe_product_id VARCHAR(255) NOT NULL,
    stripe_price_id VARCHAR(255) NOT NULL,

    unit_amount_cents INTEGER NOT NULL,

    currency VARCHAR(3)
        NOT NULL DEFAULT 'usd',

    is_active BOOLEAN
        NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_stripe_price_environment
        CHECK (
            environment IN ('test', 'live')
        ),

    CONSTRAINT chk_stripe_price_item_kind
        CHECK (
            item_kind IN (
                'base_plan',
                'sms_addon',
                'ten_dlc_assistance'
            )
        ),

    CONSTRAINT chk_stripe_price_interval
        CHECK (
            billing_interval IN (
                'month',
                'year',
                'one_time'
            )
        ),

    CONSTRAINT chk_stripe_price_amount
        CHECK (
            unit_amount_cents >= 0
        ),

    CONSTRAINT chk_stripe_price_currency
        CHECK (
            currency = LOWER(currency)
            AND CHAR_LENGTH(currency) = 3
        ),

    CONSTRAINT chk_stripe_price_shape
        CHECK (
            (
                item_kind = 'base_plan'
                AND tier_code IS NOT NULL
                AND billing_interval IN ('month', 'year')
            )
            OR
            (
                item_kind = 'sms_addon'
                AND tier_code IS NULL
                AND billing_interval IN ('month', 'year')
            )
            OR
            (
                item_kind = 'ten_dlc_assistance'
                AND tier_code IS NULL
                AND billing_interval = 'one_time'
            )
        ),

    CONSTRAINT fk_stripe_price_tier
        FOREIGN KEY (tier_code)
        REFERENCES subscription_tiers(tier_code)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_stripe_price_catalog_price
ON stripe_price_catalog (
    environment,
    stripe_price_id
);


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_stripe_price_catalog_active_mapping
ON stripe_price_catalog (
    environment,
    item_kind,
    COALESCE(tier_code, ''),
    billing_interval
)
WHERE is_active = TRUE;


CREATE INDEX IF NOT EXISTS
    idx_stripe_price_catalog_lookup
ON stripe_price_catalog (
    environment,
    item_kind,
    tier_code,
    billing_interval,
    is_active
);


COMMIT;
