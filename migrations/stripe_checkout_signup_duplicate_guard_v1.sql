BEGIN;

-- ============================================================
-- PEACH SUITE PRO
-- STRIPE CHECKOUT SIGNUP DUPLICATE GUARD V1
--
-- Prevents more than one active public subscription signup for
-- the same normalized owner email, Stripe environment, and tier.
--
-- Expired, canceled, and error attempts do not block a future
-- legitimate signup.
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_stripe_signup_active_owner_email_tier
ON stripe_checkout_signups (
    environment,
    LOWER(owner_email),
    tier_code
)
WHERE signup_status IN (
    'pending',
    'checkout_created',
    'checkout_completed',
    'provisioned'
);

COMMIT;
