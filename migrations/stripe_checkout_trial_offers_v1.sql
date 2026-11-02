-- Stripe signup trial authorization.
-- Compatible with existing Solo signups.

ALTER TABLE stripe_checkout_signups
    ADD COLUMN IF NOT EXISTS
        trial_period_days INTEGER NOT NULL DEFAULT 10,
    ADD COLUMN IF NOT EXISTS
        trial_offer_key VARCHAR(40);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'stripe_signup_trial_selection_ck'
          AND conrelid = 'stripe_checkout_signups'::regclass
    ) THEN
        ALTER TABLE stripe_checkout_signups
            ADD CONSTRAINT stripe_signup_trial_selection_ck
            CHECK (
                (
                    trial_period_days = 10
                    AND trial_offer_key IS NULL
                )
                OR
                (
                    tier_code = 'pos'
                    AND trial_period_days = 60
                    AND trial_offer_key = 'katzz60'
                )
            );
    END IF;
END
$$;

-- Reserve each private offer for one active signup.
-- Sandbox and Live are independent environments.

CREATE UNIQUE INDEX IF NOT EXISTS
    stripe_signup_active_trial_offer_uidx
ON stripe_checkout_signups (
    environment,
    trial_offer_key
)
WHERE trial_offer_key IS NOT NULL
  AND signup_status IN (
      'pending',
      'checkout_created',
      'checkout_completed',
      'provisioned'
  );
