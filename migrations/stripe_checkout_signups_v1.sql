BEGIN;

-- ============================================================
-- PEACH SUITE PRO
-- STRIPE CHECKOUT SIGNUPS V1
--
-- Holds public subscription signup data before a Stripe Checkout
-- session is confirmed and before the PSP business is provisioned.
--
-- Stripe metadata receives only checkout_signup_token.
-- Private business/owner data remains in PSP.
-- ============================================================

CREATE TABLE IF NOT EXISTS stripe_checkout_signups (
    stripe_checkout_signup_id BIGSERIAL PRIMARY KEY,

    checkout_signup_token VARCHAR(64) NOT NULL,

    environment VARCHAR(20)
        NOT NULL DEFAULT 'test',

    signup_status VARCHAR(30)
        NOT NULL DEFAULT 'pending',

    -- Selected PSP subscription
    tier_code VARCHAR(30) NOT NULL,
    billing_interval VARCHAR(20) NOT NULL,

    provider_quantity INTEGER
        NOT NULL DEFAULT 1,

    -- Optional paid add-ons
    sms_addon_selected BOOLEAN
        NOT NULL DEFAULT FALSE,

    ten_dlc_assistance_selected BOOLEAN
        NOT NULL DEFAULT FALSE,

    -- Validated PSP discount classification only.
    -- Never store the submitted private Friends/Family code here.
    discount_key VARCHAR(30),

    -- Prospective business / owner information
    business_name VARCHAR(150) NOT NULL,
    owner_first_name VARCHAR(100) NOT NULL,
    owner_last_name VARCHAR(100) NOT NULL,
    owner_email VARCHAR(255) NOT NULL,
    owner_phone VARCHAR(30),
    timezone_name VARCHAR(100) NOT NULL,

    -- Signup agreement evidence
    terms_version VARCHAR(100),
    terms_accepted_at TIMESTAMPTZ,

    -- Stripe Checkout identifiers
    stripe_checkout_session_id VARCHAR(255),
    stripe_customer_id VARCHAR(255),
    stripe_subscription_id VARCHAR(255),

    -- Populated only after successful PSP provisioning
    spa_id INTEGER,

    checkout_expires_at TIMESTAMPTZ,
    checkout_completed_at TIMESTAMPTZ,
    provisioned_at TIMESTAMPTZ,
    canceled_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_stripe_signup_environment
        CHECK (
            environment IN ('test', 'live')
        ),

    CONSTRAINT chk_stripe_signup_status
        CHECK (
            signup_status IN (
                'pending',
                'checkout_created',
                'checkout_completed',
                'provisioned',
                'expired',
                'canceled',
                'error'
            )
        ),

    CONSTRAINT chk_stripe_signup_interval
        CHECK (
            billing_interval IN ('month', 'year')
        ),

    CONSTRAINT chk_stripe_signup_provider_quantity
        CHECK (
            provider_quantity > 0
        ),

    CONSTRAINT chk_stripe_signup_discount
        CHECK (
            discount_key IS NULL
            OR discount_key IN (
                'launch10',
                'friends_family'
            )
        ),

    CONSTRAINT fk_stripe_signup_tier
        FOREIGN KEY (tier_code)
        REFERENCES subscription_tiers(tier_code)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_stripe_signup_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE SET NULL,

    CONSTRAINT uq_stripe_signup_token
        UNIQUE (checkout_signup_token)
);


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_stripe_signup_checkout_session
ON stripe_checkout_signups (
    environment,
    stripe_checkout_session_id
)
WHERE stripe_checkout_session_id IS NOT NULL;


CREATE INDEX IF NOT EXISTS
    idx_stripe_signup_status
ON stripe_checkout_signups (
    environment,
    signup_status,
    created_at
);


CREATE INDEX IF NOT EXISTS
    idx_stripe_signup_email
ON stripe_checkout_signups (
    LOWER(owner_email)
);


COMMIT;
