BEGIN;

-- ============================================================
-- PEACH SUITE PRO
-- STRIPE BILLING FOUNDATION V1
--
-- Stripe billing state is intentionally separate from:
--
--   1. PSP subscription tier / feature entitlements
--   2. Workspace permissions
--   3. Employee Verification / PSP Access Levels
--   4. PSP-facing spas.subscription_status
--
-- One business may have one Stripe billing relationship per
-- Stripe environment. Complimentary/non-Stripe businesses do
-- not require a row.
--
-- Recurring Stripe items are stored separately so one
-- subscription can contain:
--
--   - one base PSP plan
--   - optional outbound SMS
--
-- One-time 10DLC Setup Assistance is NOT a subscription item.
-- ============================================================


-- ============================================================
-- 1. STRIPE BILLING ACCOUNTS
-- ============================================================

CREATE TABLE IF NOT EXISTS stripe_billing_accounts (
    stripe_billing_account_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,

    environment VARCHAR(20)
        NOT NULL DEFAULT 'test',

    stripe_customer_id VARCHAR(255),
    stripe_subscription_id VARCHAR(255),

    stripe_subscription_status VARCHAR(40),

    trial_start TIMESTAMPTZ,
    trial_end TIMESTAMPTZ,

    cancel_at_period_end BOOLEAN
        NOT NULL DEFAULT FALSE,

    cancel_at TIMESTAMPTZ,
    canceled_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,

    last_synced_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_stripe_billing_environment
        CHECK (
            environment IN ('test', 'live')
        ),

    CONSTRAINT fk_stripe_billing_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_stripe_billing_spa_environment
        UNIQUE (
            spa_id,
            environment
        ),

    CONSTRAINT uq_stripe_billing_account_identity
        UNIQUE (
            stripe_billing_account_id,
            spa_id,
            environment
        )
);


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_stripe_billing_customer_environment
ON stripe_billing_accounts (
    environment,
    stripe_customer_id
)
WHERE stripe_customer_id IS NOT NULL;


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_stripe_billing_subscription_environment
ON stripe_billing_accounts (
    environment,
    stripe_subscription_id
)
WHERE stripe_subscription_id IS NOT NULL;


CREATE INDEX IF NOT EXISTS
    idx_stripe_billing_subscription_status
ON stripe_billing_accounts (
    environment,
    stripe_subscription_status
);


-- ============================================================
-- 2. STRIPE SUBSCRIPTION ITEMS
--
-- The base plan and recurring add-ons are separate Stripe
-- subscription items.
--
-- Examples:
--
--   base_plan:
--       Solo / PeachPOS / Team / Collective
--
--   sms_addon:
--       $5/month or $60/year
--
-- Quantity supports future per-provider Collective billing.
-- Price/product identifiers are provider metadata only.
-- PSP feature authorization continues to use subscription tiers.
-- ============================================================

CREATE TABLE IF NOT EXISTS stripe_subscription_items (
    stripe_subscription_item_id BIGSERIAL PRIMARY KEY,

    stripe_billing_account_id BIGINT NOT NULL,

    spa_id INTEGER NOT NULL,

    environment VARCHAR(20) NOT NULL,

    item_kind VARCHAR(30) NOT NULL,

    stripe_item_id VARCHAR(255) NOT NULL,
    stripe_product_id VARCHAR(255),
    stripe_price_id VARCHAR(255) NOT NULL,

    billing_interval VARCHAR(20) NOT NULL,

    quantity INTEGER NOT NULL DEFAULT 1,

    unit_amount_cents INTEGER,
    currency VARCHAR(10),

    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_stripe_item_environment
        CHECK (
            environment IN ('test', 'live')
        ),

    CONSTRAINT chk_stripe_item_kind
        CHECK (
            item_kind IN (
                'base_plan',
                'sms_addon'
            )
        ),

    CONSTRAINT chk_stripe_item_interval
        CHECK (
            billing_interval IN ('month', 'year')
        ),

    CONSTRAINT chk_stripe_item_quantity
        CHECK (
            quantity > 0
        ),

    CONSTRAINT chk_stripe_item_amount
        CHECK (
            unit_amount_cents IS NULL
            OR unit_amount_cents >= 0
        ),

    CONSTRAINT fk_stripe_item_billing_account
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

    CONSTRAINT fk_stripe_item_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_stripe_item_environment_identity
        UNIQUE (
            environment,
            stripe_item_id
        )
);


CREATE INDEX IF NOT EXISTS
    idx_stripe_items_billing_account
ON stripe_subscription_items (
    stripe_billing_account_id,
    is_active
);


CREATE INDEX IF NOT EXISTS
    idx_stripe_items_spa
ON stripe_subscription_items (
    spa_id,
    environment,
    item_kind,
    is_active
);


-- Only one active base-plan item may exist for one billing account.
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_stripe_active_base_plan
ON stripe_subscription_items (
    stripe_billing_account_id
)
WHERE item_kind = 'base_plan'
  AND is_active = TRUE;


-- Only one active SMS add-on may exist for one billing account.
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_stripe_active_sms_addon
ON stripe_subscription_items (
    stripe_billing_account_id
)
WHERE item_kind = 'sms_addon'
  AND is_active = TRUE;


-- ============================================================
-- 3. STRIPE WEBHOOK EVENT LOG
--
-- Store authenticated Stripe event IDs durably so webhook
-- processing can be idempotent.
--
-- A valid Stripe event may arrive before PSP can associate it
-- with a business, so spa_id and billing-account ID remain
-- nullable.
-- ============================================================

CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    stripe_webhook_event_id BIGSERIAL PRIMARY KEY,

    environment VARCHAR(20) NOT NULL,

    stripe_event_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(255) NOT NULL,

    stripe_customer_id VARCHAR(255),
    stripe_subscription_id VARCHAR(255),

    stripe_billing_account_id BIGINT,
    spa_id INTEGER,

    processing_status VARCHAR(30)
        NOT NULL DEFAULT 'received',

    payload JSONB NOT NULL,

    processing_attempts INTEGER
        NOT NULL DEFAULT 0,

    error_message TEXT,

    received_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    processed_at TIMESTAMPTZ,

    CONSTRAINT chk_stripe_webhook_environment
        CHECK (
            environment IN ('test', 'live')
        ),

    CONSTRAINT chk_stripe_webhook_processing_status
        CHECK (
            processing_status IN (
                'received',
                'processing',
                'processed',
                'ignored',
                'error'
            )
        ),

    CONSTRAINT fk_stripe_webhook_billing_account
        FOREIGN KEY (stripe_billing_account_id)
        REFERENCES stripe_billing_accounts(
            stripe_billing_account_id
        )
        ON DELETE SET NULL,

    CONSTRAINT fk_stripe_webhook_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE SET NULL,

    CONSTRAINT uq_stripe_webhook_event
        UNIQUE (
            environment,
            stripe_event_id
        )
);


CREATE INDEX IF NOT EXISTS
    idx_stripe_webhook_processing
ON stripe_webhook_events (
    environment,
    processing_status,
    received_at
);


CREATE INDEX IF NOT EXISTS
    idx_stripe_webhook_customer
ON stripe_webhook_events (
    environment,
    stripe_customer_id
)
WHERE stripe_customer_id IS NOT NULL;


CREATE INDEX IF NOT EXISTS
    idx_stripe_webhook_subscription
ON stripe_webhook_events (
    environment,
    stripe_subscription_id
)
WHERE stripe_subscription_id IS NOT NULL;


COMMIT;
