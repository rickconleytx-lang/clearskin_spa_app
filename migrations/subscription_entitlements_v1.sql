BEGIN;

-- ============================================================
-- PEACH SUITE PRO
-- SUBSCRIPTION ENTITLEMENTS V1
--
-- Commercial subscription capabilities are intentionally
-- separate from:
--
--   1. Workspace permissions
--   2. Employee Verification / PSP Access Levels
--   3. Account/subscription billing metadata on spas
--
-- Application authorization order:
--
--   Subscription entitlement
--       -> Workspace permission
--       -> Employee Verification / PSP Access when required
--
-- Application code must check feature keys, never plan names.
-- Absence of a tier/feature row means NOT ENTITLED.
-- ============================================================


-- ============================================================
-- 1. COMMERCIAL TIERS
--
-- Preserve the existing Solo, Team, and legacy Enterprise rows.
-- Add the two commercial tiers that do not yet exist.
-- ============================================================

INSERT INTO subscription_tiers (
    tier_code,
    tier_name,
    display_order,
    is_active
)
VALUES
    ('pos', 'POS', 5, TRUE),
    ('collective', 'Peach Collective', 25, TRUE)
ON CONFLICT (tier_code)
DO UPDATE SET
    tier_name = EXCLUDED.tier_name,
    display_order = EXCLUDED.display_order,
    is_active = EXCLUDED.is_active;


-- ============================================================
-- 2. SUBSCRIPTION FEATURE CATALOG
-- ============================================================

CREATE TABLE IF NOT EXISTS subscription_features (
    subscription_feature_id SERIAL PRIMARY KEY,

    feature_key VARCHAR(64) NOT NULL UNIQUE,
    feature_name VARCHAR(100) NOT NULL,
    feature_description TEXT,

    display_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_subscription_features_key
        CHECK (
            feature_key = LOWER(feature_key)
            AND feature_key ~ '^[a-z0-9_]+$'
        )
);


-- ============================================================
-- 3. BASE TIER -> FEATURE ENTITLEMENTS
--
-- One row means the base subscription tier includes the feature.
-- Missing row means the feature is not included.
--
-- Future account-level add-ons/overrides are deliberately NOT
-- modeled here. SMS and optional/shared Collective PeachWeb
-- remain separate product decisions.
-- ============================================================

CREATE TABLE IF NOT EXISTS subscription_tier_features (
    subscription_tier_feature_id SERIAL PRIMARY KEY,

    subscription_tier_id INTEGER NOT NULL,
    subscription_feature_id INTEGER NOT NULL,

    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_subscription_tier_feature
        UNIQUE (
            subscription_tier_id,
            subscription_feature_id
        ),

    CONSTRAINT fk_subscription_tier_feature_tier
        FOREIGN KEY (subscription_tier_id)
        REFERENCES subscription_tiers(subscription_tier_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_subscription_tier_feature_feature
        FOREIGN KEY (subscription_feature_id)
        REFERENCES subscription_features(subscription_feature_id)
        ON DELETE RESTRICT
);


CREATE INDEX IF NOT EXISTS
idx_subscription_tier_features_feature
ON subscription_tier_features (
    subscription_feature_id,
    subscription_tier_id
);


-- ============================================================
-- 4. FEATURE CATALOG
--
-- Do not add:
--   - Backups: platform/service-level capability
--   - Existing Website Support: removed as a standalone feature
--   - SMS: commercial/add-on behavior not yet finalized
--
-- Event Calendar is cataloged for POS even though its product UI
-- is intentionally deferred from the initial launch.
-- ============================================================

INSERT INTO subscription_features (
    feature_key,
    feature_name,
    feature_description,
    display_order,
    is_active
)
VALUES
    (
        'peachbook',
        'PeachBook',
        'Public online appointment booking.',
        10,
        TRUE
    ),
    (
        'clients',
        'Client Management',
        'Client records and client-management workflows.',
        20,
        TRUE
    ),
    (
        'event_calendar',
        'Event Calendar',
        'General business events, locations, pop-ups, and operating stops.',
        30,
        TRUE
    ),
    (
        'appointments',
        'Appointments',
        'Appointment scheduling and appointment-calendar workflows.',
        40,
        TRUE
    ),
    (
        'income_expenses',
        'Income & Expenses',
        'Business income and expense accounting.',
        50,
        TRUE
    ),
    (
        'business_loans',
        'Business Loans',
        'Business loan tracking and loan activity.',
        60,
        TRUE
    ),
    (
        'inventory',
        'Inventory',
        'Inventory management and inventory sales activity.',
        70,
        TRUE
    ),
    (
        'square_integration',
        'Square Integration',
        'Square synchronization, payments, and reconciliation.',
        80,
        TRUE
    ),
    (
        'email_messaging',
        'Email',
        'Business email communication capabilities.',
        90,
        TRUE
    ),
    (
        'coach_peach',
        'Coach Peach',
        'Coach Peach business briefing and operational insights.',
        100,
        TRUE
    ),
    (
        'peachweb',
        'PeachWeb',
        'Peach Suite Pro hosted public website.',
        110,
        TRUE
    ),
    (
        'employees',
        'Employees',
        'Employee records and employee-management workflows.',
        120,
        TRUE
    ),
    (
        'business_user_management',
        'Multiple Users',
        'Create and manage multiple PSP login users within a workspace.',
        130,
        TRUE
    ),
    (
        'independent_workspaces',
        'Independent Workspaces',
        'Create and operate independent provider workspaces under one business.',
        140,
        TRUE
    ),
    (
        'birthdays',
        'Birthdays',
        'Client birthday workflows and offers.',
        150,
        TRUE
    ),
    (
        'gift_certificates',
        'Gift Certificates',
        'Client gift certificate workflows.',
        160,
        TRUE
    ),
    (
        'import_export',
        'Import / Export',
        'Customer-facing data import and export capabilities.',
        170,
        TRUE
    )
ON CONFLICT (feature_key)
DO UPDATE SET
    feature_name = EXCLUDED.feature_name,
    feature_description = EXCLUDED.feature_description,
    display_order = EXCLUDED.display_order,
    is_active = EXCLUDED.is_active;


-- ============================================================
-- 5. POS BASE ENTITLEMENTS
-- ============================================================

INSERT INTO subscription_tier_features (
    subscription_tier_id,
    subscription_feature_id
)
SELECT
    st.subscription_tier_id,
    sf.subscription_feature_id
FROM subscription_tiers st
JOIN subscription_features sf
  ON sf.feature_key IN (
        'event_calendar',
        'income_expenses',
        'business_loans',
        'inventory',
        'square_integration',
        'email_messaging',
        'coach_peach',
        'peachweb',
        'employees',
        'import_export'
     )
WHERE st.tier_code = 'pos'
  AND st.is_active = TRUE
  AND sf.is_active = TRUE
ON CONFLICT (
    subscription_tier_id,
    subscription_feature_id
)
DO NOTHING;


-- ============================================================
-- 6. SOLO BASE ENTITLEMENTS
-- ============================================================

INSERT INTO subscription_tier_features (
    subscription_tier_id,
    subscription_feature_id
)
SELECT
    st.subscription_tier_id,
    sf.subscription_feature_id
FROM subscription_tiers st
JOIN subscription_features sf
  ON sf.feature_key IN (
        'peachbook',
        'clients',
        'appointments',
        'income_expenses',
        'business_loans',
        'inventory',
        'square_integration',
        'email_messaging',
        'coach_peach',
        'peachweb',
        'birthdays',
        'gift_certificates',
        'import_export'
     )
WHERE st.tier_code = 'solo'
  AND st.is_active = TRUE
  AND sf.is_active = TRUE
ON CONFLICT (
    subscription_tier_id,
    subscription_feature_id
)
DO NOTHING;


-- ============================================================
-- 7. TEAM BASE ENTITLEMENTS
-- ============================================================

INSERT INTO subscription_tier_features (
    subscription_tier_id,
    subscription_feature_id
)
SELECT
    st.subscription_tier_id,
    sf.subscription_feature_id
FROM subscription_tiers st
JOIN subscription_features sf
  ON sf.feature_key IN (
        'peachbook',
        'clients',
        'appointments',
        'income_expenses',
        'business_loans',
        'inventory',
        'square_integration',
        'email_messaging',
        'coach_peach',
        'peachweb',
        'employees',
        'business_user_management',
        'birthdays',
        'gift_certificates',
        'import_export'
     )
WHERE st.tier_code = 'team'
  AND st.is_active = TRUE
  AND sf.is_active = TRUE
ON CONFLICT (
    subscription_tier_id,
    subscription_feature_id
)
DO NOTHING;


-- ============================================================
-- 8. PEACH COLLECTIVE BASE ENTITLEMENTS
--
-- PeachWeb is intentionally absent here because the current
-- product matrix defines it as Optional / Shared.
--
-- Employee Management and ordinary Multiple Users are also
-- intentionally absent. Collective provider-user provisioning
-- belongs to the Independent Workspaces workflow instead.
-- ============================================================

INSERT INTO subscription_tier_features (
    subscription_tier_id,
    subscription_feature_id
)
SELECT
    st.subscription_tier_id,
    sf.subscription_feature_id
FROM subscription_tiers st
JOIN subscription_features sf
  ON sf.feature_key IN (
        'peachbook',
        'clients',
        'appointments',
        'income_expenses',
        'business_loans',
        'inventory',
        'square_integration',
        'email_messaging',
        'coach_peach',
        'independent_workspaces',
        'birthdays',
        'gift_certificates',
        'import_export'
     )
WHERE st.tier_code = 'collective'
  AND st.is_active = TRUE
  AND sf.is_active = TRUE
ON CONFLICT (
    subscription_tier_id,
    subscription_feature_id
)
DO NOTHING;


-- ============================================================
-- 9. LEGACY ENTERPRISE
--
-- Enterprise remains in subscription_tiers for compatibility.
-- No V1 entitlement assumptions are made for it because there
-- are currently no businesses assigned to that tier.
-- ============================================================


COMMIT;
