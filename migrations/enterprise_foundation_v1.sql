BEGIN;

-- =========================================================
-- 1. SUBSCRIPTION TIERS
-- =========================================================

CREATE TABLE IF NOT EXISTS subscription_tiers (
    subscription_tier_id SERIAL PRIMARY KEY,
    tier_code VARCHAR(30) NOT NULL UNIQUE,
    tier_name VARCHAR(75) NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO subscription_tiers (
    tier_code,
    tier_name,
    display_order,
    is_active
)
VALUES
    ('solo', 'Solo', 10, TRUE),
    ('team', 'Team', 20, TRUE),
    ('enterprise', 'Enterprise', 30, TRUE)
ON CONFLICT (tier_code)
DO UPDATE SET
    tier_name = EXCLUDED.tier_name,
    display_order = EXCLUDED.display_order,
    is_active = EXCLUDED.is_active;


-- =========================================================
-- 2. ORGANIZATION TYPES
-- =========================================================

CREATE TABLE IF NOT EXISTS organization_types (
    organization_type_id SERIAL PRIMARY KEY,
    type_code VARCHAR(40) NOT NULL UNIQUE,
    type_name VARCHAR(100) NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO organization_types (
    type_code,
    type_name,
    display_order,
    is_active
)
VALUES
    ('solo_owner', 'Solo Owner', 10, TRUE),
    ('employees', 'Employees', 20, TRUE),
    ('independent_providers', 'Independent Providers', 30, TRUE),
    ('mixed_team', 'Mixed Team', 40, TRUE)
ON CONFLICT (type_code)
DO UPDATE SET
    type_name = EXCLUDED.type_name,
    display_order = EXCLUDED.display_order,
    is_active = EXCLUDED.is_active;


-- =========================================================
-- 3. CONNECT SPAS TO THE NEW FOUNDATION
-- =========================================================

ALTER TABLE spas
ADD COLUMN IF NOT EXISTS subscription_tier_id INTEGER;

ALTER TABLE spas
ADD COLUMN IF NOT EXISTS organization_type_id INTEGER;


-- Existing spas begin as Solo / Solo Owner.

UPDATE spas
SET subscription_tier_id = (
    SELECT subscription_tier_id
    FROM subscription_tiers
    WHERE tier_code = 'solo'
)
WHERE subscription_tier_id IS NULL;


UPDATE spas
SET organization_type_id = (
    SELECT organization_type_id
    FROM organization_types
    WHERE type_code = 'solo_owner'
)
WHERE organization_type_id IS NULL;


ALTER TABLE spas
ALTER COLUMN subscription_tier_id SET NOT NULL;

ALTER TABLE spas
ALTER COLUMN organization_type_id SET NOT NULL;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_spas_subscription_tier'
    ) THEN
        ALTER TABLE spas
        ADD CONSTRAINT fk_spas_subscription_tier
        FOREIGN KEY (subscription_tier_id)
        REFERENCES subscription_tiers(subscription_tier_id);
    END IF;
END
$$;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_spas_organization_type'
    ) THEN
        ALTER TABLE spas
        ADD CONSTRAINT fk_spas_organization_type
        FOREIGN KEY (organization_type_id)
        REFERENCES organization_types(organization_type_id);
    END IF;
END
$$;


-- =========================================================
-- 4. BUSINESS UNITS
-- Database term: business unit
-- User-facing term: Provider Workspace
-- =========================================================

CREATE TABLE IF NOT EXISTS business_units (
    business_unit_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,

    unit_name VARCHAR(150) NOT NULL,

    unit_type VARCHAR(40)
        NOT NULL DEFAULT 'organization',

    owner_employee_id INTEGER,

    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP WITHOUT TIME ZONE,

    created_by INTEGER,
    updated_by INTEGER,

    CONSTRAINT fk_business_units_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_business_units_owner_employee
        FOREIGN KEY (owner_employee_id)
        REFERENCES employees(employee_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_business_units_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_business_units_updated_by
        FOREIGN KEY (updated_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT chk_business_units_unit_type
        CHECK (
            unit_type IN (
                'organization',
                'independent_provider'
            )
        )
);


CREATE UNIQUE INDEX IF NOT EXISTS
uq_business_units_default_per_spa
ON business_units (spa_id)
WHERE is_default = TRUE;


CREATE INDEX IF NOT EXISTS
idx_business_units_spa_active
ON business_units (spa_id, is_active);


-- Create one default organization workspace for every spa.

INSERT INTO business_units (
    spa_id,
    unit_name,
    unit_type,
    is_default,
    is_active
)
SELECT
    s.spa_id,
    s.spa_name,
    'organization',
    TRUE,
    TRUE
FROM spas s
WHERE NOT EXISTS (
    SELECT 1
    FROM business_units bu
    WHERE bu.spa_id = s.spa_id
      AND bu.is_default = TRUE
);


-- =========================================================
-- 5. BUSINESS-UNIT MEMBERSHIPS
-- =========================================================

CREATE TABLE IF NOT EXISTS business_unit_memberships (
    business_unit_membership_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,

    membership_role_code VARCHAR(40) NOT NULL,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    granted_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    granted_by INTEGER,

    revoked_at TIMESTAMP WITHOUT TIME ZONE,
    revoked_by INTEGER,

    CONSTRAINT fk_business_unit_memberships_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_business_unit_memberships_unit
        FOREIGN KEY (business_unit_id)
        REFERENCES business_units(business_unit_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_business_unit_memberships_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_business_unit_memberships_granted_by
        FOREIGN KEY (granted_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_business_unit_memberships_revoked_by
        FOREIGN KEY (revoked_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT chk_business_unit_membership_role
        CHECK (
            membership_role_code IN (
                'organization_owner',
                'organization_admin',
                'independent_provider',
                'scheduler',
                'bookkeeper'
            )
        )
);


CREATE UNIQUE INDEX IF NOT EXISTS
uq_business_unit_active_membership
ON business_unit_memberships (
    business_unit_id,
    user_id
)
WHERE is_active = TRUE;


CREATE INDEX IF NOT EXISTS
idx_business_unit_memberships_user
ON business_unit_memberships (
    user_id,
    is_active
);


CREATE INDEX IF NOT EXISTS
idx_business_unit_memberships_spa
ON business_unit_memberships (
    spa_id,
    is_active
);


-- Give existing active admin/master-admin users access
-- to their spa's default organization workspace.
--
-- Existing users.role values are not changed.

INSERT INTO business_unit_memberships (
    spa_id,
    business_unit_id,
    user_id,
    membership_role_code,
    is_active
)
SELECT
    u.spa_id,
    bu.business_unit_id,
    u.user_id,
    'organization_admin',
    TRUE
FROM users u

JOIN business_units bu
  ON bu.spa_id = u.spa_id
 AND bu.is_default = TRUE

WHERE u.active = TRUE
  AND u.spa_id IS NOT NULL
  AND u.role IN ('admin', 'master_admin')

  AND NOT EXISTS (
      SELECT 1
      FROM business_unit_memberships bum
      WHERE bum.business_unit_id = bu.business_unit_id
        AND bum.user_id = u.user_id
        AND bum.is_active = TRUE
  );


COMMIT;