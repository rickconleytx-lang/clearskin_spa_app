BEGIN;

-- ============================================================
-- PEACH SUITE PRO
-- STRIPE RESUBSCRIPTIONS V1
--
-- Durable lifecycle for an EXISTING PSP business returning to
-- paid Stripe billing after its prior subscription has ended.
--
-- This is intentionally separate from stripe_checkout_signups:
--
--   stripe_checkout_signups -> brand-new business provisioning
--   stripe_resubscriptions  -> restore an existing business
--
-- A resubscription:
--   - reuses the existing PSP business
--   - reuses the existing Stripe customer
--   - creates a NEW Stripe subscription
--   - never provisions another PSP business
--   - does not grant another introductory trial
-- ============================================================


CREATE TABLE IF NOT EXISTS stripe_resubscriptions (
    stripe_resubscription_id BIGSERIAL PRIMARY KEY,

    resubscription_token VARCHAR(64) NOT NULL,

    environment VARCHAR(20)
        NOT NULL DEFAULT 'test',

    resubscription_status VARCHAR(30)
        NOT NULL DEFAULT 'pending',

    -- Existing PSP identity
    spa_id INTEGER NOT NULL,
    stripe_billing_account_id BIGINT NOT NULL,

    -- Requested subscription configuration
    tier_code VARCHAR(30) NOT NULL,
    billing_interval VARCHAR(20) NOT NULL,

    provider_quantity INTEGER
        NOT NULL DEFAULT 1,

    -- Who initiated the PSP resubscription flow.
    initiated_by_user_id INTEGER,

    -- Current subscription-terms acceptance for this attempt.
    terms_version VARCHAR(100),
    terms_accepted_at TIMESTAMPTZ,

    -- Existing Stripe customer is retained.
    stripe_customer_id VARCHAR(255) NOT NULL,

    -- Historical subscription being replaced.
    previous_stripe_subscription_id VARCHAR(255),

    -- New Stripe Checkout / Subscription identities.
    stripe_checkout_session_id VARCHAR(255),
    stripe_subscription_id VARCHAR(255),

    checkout_expires_at TIMESTAMPTZ,
    checkout_completed_at TIMESTAMPTZ,
    activated_at TIMESTAMPTZ,
    canceled_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_stripe_resub_environment
        CHECK (
            environment IN ('test', 'live')
        ),

    CONSTRAINT chk_stripe_resub_status
        CHECK (
            resubscription_status IN (
                'pending',
                'checkout_created',
                'checkout_completed',
                'activated',
                'expired',
                'canceled',
                'error'
            )
        ),

    CONSTRAINT chk_stripe_resub_interval
        CHECK (
            billing_interval IN ('month', 'year')
        ),

    CONSTRAINT chk_stripe_resub_provider_quantity
        CHECK (
            provider_quantity > 0
        ),

    CONSTRAINT fk_stripe_resub_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_stripe_resub_tier
        FOREIGN KEY (tier_code)
        REFERENCES subscription_tiers(tier_code)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_stripe_resub_user
        FOREIGN KEY (initiated_by_user_id)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_stripe_resub_billing_account
        FOREIGN KEY (
            stripe_billing_account_id,
            spa_id,
            environment
        )
        REFERENCES stripe_billing_accounts(
            stripe_billing_account_id,
            spa_id,
            environment
        )
        ON DELETE CASCADE,

    CONSTRAINT uq_stripe_resub_token
        UNIQUE (resubscription_token)
);


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_stripe_resub_checkout_session
ON stripe_resubscriptions (
    environment,
    stripe_checkout_session_id
)
WHERE stripe_checkout_session_id IS NOT NULL;


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_stripe_resub_subscription
ON stripe_resubscriptions (
    environment,
    stripe_subscription_id
)
WHERE stripe_subscription_id IS NOT NULL;


-- A business may have historical attempts, but only one unresolved
-- resubscription workflow at a time in one Stripe environment.
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_stripe_resub_open_attempt
ON stripe_resubscriptions (
    spa_id,
    environment
)
WHERE resubscription_status IN (
    'pending',
    'checkout_created',
    'checkout_completed'
);


CREATE INDEX IF NOT EXISTS
    idx_stripe_resub_status
ON stripe_resubscriptions (
    environment,
    resubscription_status,
    created_at
);


CREATE INDEX IF NOT EXISTS
    idx_stripe_resub_billing_account
ON stripe_resubscriptions (
    stripe_billing_account_id,
    environment,
    created_at
);


COMMENT ON TABLE stripe_resubscriptions IS
    'Existing-business Stripe resubscription lifecycle. Reuses the '
    'existing PSP business and Stripe customer and creates a new '
    'Stripe subscription without provisioning another business.';


COMMIT;
