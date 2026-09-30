BEGIN;

-- ============================================================
-- PEACH SUITE PRO
-- PRE-CHECKOUT PHONE VERIFICATION V1
--
-- Verifies the prospective Owner's personal mobile number
-- before Stripe Checkout and business provisioning.
--
-- Security policy mirrors PSP MFA:
--   code lifetime:        10 minutes
--   resend cooldown:      60 seconds
--   max deliveries:       3 per hour
--   failed attempts:      5 within 15 minutes
--   lockout:              15 minutes
--
-- Raw verification codes are NEVER stored.
-- ============================================================


ALTER TABLE stripe_checkout_signups
    ADD COLUMN IF NOT EXISTS
        phone_verified_at TIMESTAMPTZ,

    ADD COLUMN IF NOT EXISTS
        phone_verification_failed_count INTEGER
            NOT NULL DEFAULT 0,

    ADD COLUMN IF NOT EXISTS
        phone_verification_window_started_at TIMESTAMPTZ,

    ADD COLUMN IF NOT EXISTS
        phone_verification_last_failed_at TIMESTAMPTZ,

    ADD COLUMN IF NOT EXISTS
        phone_verification_locked_until TIMESTAMPTZ;


ALTER TABLE stripe_checkout_signups
    DROP CONSTRAINT IF EXISTS
        chk_stripe_signup_phone_failed_count;


ALTER TABLE stripe_checkout_signups
    ADD CONSTRAINT
        chk_stripe_signup_phone_failed_count
    CHECK (
        phone_verification_failed_count >= 0
    );


CREATE TABLE IF NOT EXISTS
    stripe_checkout_phone_verification_challenges (
        stripe_checkout_phone_verification_challenge_id
            BIGSERIAL PRIMARY KEY,

        stripe_checkout_signup_id BIGINT NOT NULL,

        -- Snapshot of the normalized destination used for this
        -- particular verification challenge.
        phone_number VARCHAR(30) NOT NULL,

        code_hash CHAR(64) NOT NULL,

        created_at TIMESTAMPTZ
            NOT NULL DEFAULT CURRENT_TIMESTAMP,

        expires_at TIMESTAMPTZ NOT NULL,

        delivery_sent_at TIMESTAMPTZ,

        used_at TIMESTAMPTZ,

        invalidated_at TIMESTAMPTZ,

        CONSTRAINT
            fk_stripe_checkout_phone_verification_signup
        FOREIGN KEY (
            stripe_checkout_signup_id
        )
        REFERENCES stripe_checkout_signups(
            stripe_checkout_signup_id
        )
        ON DELETE CASCADE,

        CONSTRAINT
            chk_stripe_checkout_phone_code_hash
        CHECK (
            CHAR_LENGTH(code_hash) = 64
        ),

        CONSTRAINT
            chk_stripe_checkout_phone_expires
        CHECK (
            expires_at > created_at
        ),

        CONSTRAINT
            chk_stripe_checkout_phone_delivery
        CHECK (
            delivery_sent_at IS NULL
            OR (
                delivery_sent_at >= created_at
                AND delivery_sent_at <= expires_at
            )
        ),

        CONSTRAINT
            chk_stripe_checkout_phone_used
        CHECK (
            used_at IS NULL
            OR (
                used_at >= created_at
                AND used_at <= expires_at
                AND delivery_sent_at IS NOT NULL
            )
        ),

        CONSTRAINT
            chk_stripe_checkout_phone_invalidated
        CHECK (
            invalidated_at IS NULL
            OR invalidated_at >= created_at
        ),

        CONSTRAINT
            chk_stripe_checkout_phone_terminal
        CHECK (
            NOT (
                used_at IS NOT NULL
                AND invalidated_at IS NOT NULL
            )
        )
    );


CREATE INDEX IF NOT EXISTS
    idx_stripe_checkout_phone_challenge_signup_created
ON stripe_checkout_phone_verification_challenges (
    stripe_checkout_signup_id,
    created_at DESC
);


CREATE INDEX IF NOT EXISTS
    idx_stripe_checkout_phone_challenge_active
ON stripe_checkout_phone_verification_challenges (
    stripe_checkout_signup_id,
    expires_at
)
WHERE delivery_sent_at IS NOT NULL
  AND used_at IS NULL
  AND invalidated_at IS NULL;


CREATE INDEX IF NOT EXISTS
    idx_stripe_checkout_phone_challenge_phone_created
ON stripe_checkout_phone_verification_challenges (
    phone_number,
    created_at DESC
);


COMMIT;
