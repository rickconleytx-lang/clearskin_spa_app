-- Permanent, single-use Stripe trial offer redemptions.
--
-- An incomplete signup does not consume an offer.
-- A completed Stripe Checkout permanently consumes it.
-- Redemption records must survive subscription cancellation.

CREATE TABLE stripe_trial_offer_redemptions (
    stripe_trial_offer_redemption_id BIGSERIAL PRIMARY KEY,

    environment VARCHAR(16) NOT NULL
        CHECK (environment IN ('test', 'live')),

    trial_offer_key VARCHAR(40) NOT NULL
        CHECK (LENGTH(TRIM(trial_offer_key)) > 0),

    stripe_checkout_signup_id BIGINT NOT NULL
        REFERENCES stripe_checkout_signups (
            stripe_checkout_signup_id
        )
        ON DELETE RESTRICT,

    stripe_subscription_id VARCHAR(255) NOT NULL,

    redeemed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT stripe_trial_offer_redemptions_offer_uq
        UNIQUE (environment, trial_offer_key),

    CONSTRAINT stripe_trial_offer_redemptions_signup_uq
        UNIQUE (stripe_checkout_signup_id),

    CONSTRAINT stripe_trial_offer_redemptions_subscription_uq
        UNIQUE (environment, stripe_subscription_id)
);
