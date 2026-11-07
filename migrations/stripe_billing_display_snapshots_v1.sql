-- Peach Suite Pro
-- Verified Stripe billing display snapshots, v1
--
-- Does not modify Stripe subscriptions or existing billing tables.
-- All pricing records are scoped to one PSP billing account.

BEGIN;

CREATE TABLE IF NOT EXISTS stripe_billing_display_snapshots (
    stripe_billing_account_id BIGINT PRIMARY KEY,

    spa_id INTEGER NOT NULL,

    environment VARCHAR(20) NOT NULL
        CHECK (environment IN ('test', 'live')),

    stripe_subscription_id VARCHAR(255) NOT NULL,

    -- Only normalized, display-safe billing information.
    -- Never store Stripe API keys or full customer objects.
    quote_json JSONB,

    verified_at TIMESTAMPTZ,

    -- Automatic and manual refresh controls.
    last_auto_attempt_at TIMESTAMPTZ,
    last_manual_attempt_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,

    last_attempt_status VARCHAR(20)
        CHECK (
            last_attempt_status IN (
                'verified',
                'unavailable',
                'error'
            )
        ),

    -- Short-lived claim for concurrent refresh protection.
    refresh_lock_token VARCHAR(64),
    refresh_lock_expires_at TIMESTAMPTZ,

    -- Webhook changes can mark a snapshot stale.
    invalidated_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_billing_display_account
        FOREIGN KEY (
            stripe_billing_account_id,
            spa_id,
            environment
        )
        REFERENCES stripe_billing_accounts (
            stripe_billing_account_id,
            spa_id,
            environment
        )
        ON DELETE CASCADE,

    CONSTRAINT uq_billing_display_workspace
        UNIQUE (spa_id, environment),

    CONSTRAINT chk_billing_display_quote
        CHECK (
            (
                quote_json IS NULL
                AND verified_at IS NULL
            )
            OR
            (
                quote_json IS NOT NULL
                AND verified_at IS NOT NULL
                AND jsonb_typeof(quote_json) = 'object'
            )
        ),

    CONSTRAINT chk_billing_display_refresh_lock
        CHECK (
            (
                refresh_lock_token IS NULL
                AND refresh_lock_expires_at IS NULL
            )
            OR
            (
                refresh_lock_token IS NOT NULL
                AND refresh_lock_expires_at IS NOT NULL
            )
        )
);

COMMENT ON TABLE stripe_billing_display_snapshots IS
'Last verified Stripe billing display information, scoped by PSP billing account and environment.';

COMMIT;
