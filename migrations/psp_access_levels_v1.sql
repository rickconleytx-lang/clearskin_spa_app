BEGIN;

-- ============================================================
-- PEACH SUITE PRO
-- PSP ACCESS LEVELS V1
--
-- Employee Role:
--   Business-facing role/category.
--   Each business has up to five stable role slots.
--   role_name remains user-customizable.
--
-- PSP Access Level:
--   Workspace-scoped authorization level.
--
--   1 = Full Access
--   2 = Access to levels 2-5
--   3 = Access to levels 3-5
--   4 = Access to levels 4-5
--   5 = Access to level 5
--   NULL = No PSP restricted-area access
--
-- Solo Operator businesses bypass Employee Verification
-- and PSP Access Level enforcement in application logic.
-- ============================================================


-- ============================================================
-- 1. EMPLOYEE ROLE SLOTS
-- ============================================================

ALTER TABLE employee_roles
    ADD COLUMN IF NOT EXISTS role_slot SMALLINT;


-- Backfill existing employee role slots.
--
-- Role slot 1 is permanently reserved for Owner.
-- Owner is the fixed first role and is not user-renamable.
--
-- Remaining roles use slots 2-5 in each business's existing
-- display order. Those role names are business-defined and
-- do not determine PSP access authorization.

UPDATE employee_roles
SET role_slot = 1
WHERE role_slot IS NULL
  AND LOWER(BTRIM(role_name)) = 'owner';


-- Every business must have the permanent Owner role in slot 1.
-- Create it only when the business does not already have slot 1.

INSERT INTO employee_roles (
    spa_id,
    role_name,
    is_active,
    display_order,
    role_slot
)
SELECT
    s.spa_id,
    'Owner',
    TRUE,
    10,
    1
FROM spas s
WHERE NOT EXISTS (
    SELECT 1
    FROM employee_roles er
    WHERE er.spa_id = s.spa_id
      AND er.role_slot = 1
);


WITH ordered_roles AS (
    SELECT
        employee_role_id,
        ROW_NUMBER() OVER (
            PARTITION BY spa_id
            ORDER BY display_order, employee_role_id
        ) + 1 AS calculated_role_slot
    FROM employee_roles
    WHERE role_slot IS NULL
)
UPDATE employee_roles er
SET role_slot = ordered_roles.calculated_role_slot
FROM ordered_roles
WHERE er.employee_role_id = ordered_roles.employee_role_id
  AND ordered_roles.calculated_role_slot BETWEEN 2 AND 5;


-- Fail rather than silently invent a role slot.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM employee_roles
        WHERE role_slot IS NULL
    ) THEN
        RAISE EXCEPTION
            'PSP Access Levels migration found an employee role without a role_slot mapping.';
    END IF;
END
$$;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_employee_roles_role_slot'
    ) THEN
        ALTER TABLE employee_roles
            ADD CONSTRAINT chk_employee_roles_role_slot
            CHECK (role_slot BETWEEN 1 AND 5);
    END IF;
END
$$;


ALTER TABLE employee_roles
    ALTER COLUMN role_slot SET NOT NULL;


CREATE UNIQUE INDEX IF NOT EXISTS
uq_employee_roles_spa_role_slot
ON employee_roles (
    spa_id,
    role_slot
);


-- ============================================================
-- 2. WORKSPACE PSP ACCESS LEVEL
-- ============================================================

ALTER TABLE employee_business_unit_memberships
    ADD COLUMN IF NOT EXISTS access_level SMALLINT;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'chk_employee_business_unit_membership_access_level'
    ) THEN
        ALTER TABLE employee_business_unit_memberships
            ADD CONSTRAINT
                chk_employee_business_unit_membership_access_level
            CHECK (
                access_level IS NULL
                OR access_level BETWEEN 1 AND 5
            );
    END IF;
END
$$;


-- Existing Owner-role memberships receive Full Access.
-- All other employees remain NULL until explicitly assigned.

UPDATE employee_business_unit_memberships ebum
SET access_level = 1
FROM employees e
JOIN employee_roles er
  ON er.spa_id = e.spa_id
 AND er.employee_role_id = e.employee_role_id
WHERE ebum.spa_id = e.spa_id
  AND ebum.employee_id = e.employee_id
  AND er.role_slot = 1
  AND ebum.access_level IS NULL;


-- ============================================================
-- 3. PSP RESTRICTED AREA SETTINGS
-- ============================================================

CREATE TABLE IF NOT EXISTS psp_access_area_settings (
    psp_access_area_setting_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    area_key VARCHAR(64) NOT NULL,

    required_access_level SMALLINT
        NOT NULL DEFAULT 1,

    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_by INTEGER,

    updated_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_by INTEGER,

    CONSTRAINT uq_psp_access_area_settings_workspace
        UNIQUE (
            spa_id,
            business_unit_id,
            area_key
        ),

    CONSTRAINT chk_psp_access_area_required_level
        CHECK (
            required_access_level BETWEEN 1 AND 5
        ),

    CONSTRAINT chk_psp_access_area_key
        CHECK (
            area_key IN (
                'employees_compensation',
                'financial_management',
                'add_income',
                'add_expense',
                'business_goals',
                'business_users',
                'business_security'
            )
        ),

    CONSTRAINT fk_psp_access_area_business_unit
        FOREIGN KEY (
            spa_id,
            business_unit_id
        )
        REFERENCES business_units (
            spa_id,
            business_unit_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_psp_access_area_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_psp_access_area_updated_by
        FOREIGN KEY (updated_by)
        REFERENCES users(user_id)
        ON DELETE RESTRICT
);


CREATE INDEX IF NOT EXISTS
idx_psp_access_area_settings_workspace
ON psp_access_area_settings (
    spa_id,
    business_unit_id,
    area_key
);


-- Seed all seven restricted areas conservatively at Level 1.
-- The Owner may later assign Levels 2-5 through PSP settings.

INSERT INTO psp_access_area_settings (
    spa_id,
    business_unit_id,
    area_key,
    required_access_level
)
SELECT
    bu.spa_id,
    bu.business_unit_id,
    areas.area_key,
    1
FROM business_units bu
CROSS JOIN (
    VALUES
        ('employees_compensation'),
        ('financial_management'),
        ('add_income'),
        ('add_expense'),
        ('business_goals'),
        ('business_users'),
        ('business_security')
) AS areas(area_key)
ON CONFLICT (
    spa_id,
    business_unit_id,
    area_key
)
DO NOTHING;


COMMIT;
