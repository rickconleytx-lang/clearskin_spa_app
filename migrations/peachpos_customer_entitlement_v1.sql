-- PeachPOS customer-management entitlement.
-- Additive, repeat-safe migration.
-- Does not enable appointments or PeachBook.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM subscription_tiers
        WHERE tier_code = 'pos'
          AND is_active = TRUE
    ) THEN
        RAISE EXCEPTION 'Active POS tier not found';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM subscription_features
        WHERE feature_key = 'clients'
          AND is_active = TRUE
    ) THEN
        RAISE EXCEPTION 'Active clients feature not found';
    END IF;
END
$$;

INSERT INTO subscription_tier_features (
    subscription_tier_id,
    subscription_feature_id
)
SELECT
    st.subscription_tier_id,
    sf.subscription_feature_id
FROM subscription_tiers st
CROSS JOIN subscription_features sf
WHERE st.tier_code = 'pos'
  AND st.is_active = TRUE
  AND sf.feature_key = 'clients'
  AND sf.is_active = TRUE
ON CONFLICT DO NOTHING;

COMMIT;
