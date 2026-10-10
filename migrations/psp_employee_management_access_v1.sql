BEGIN;

-- PEACH SUITE PRO
-- Employee Management Access V1
-- Additive security migration.

ALTER TABLE public.psp_access_area_settings
    DROP CONSTRAINT chk_psp_access_area_key;

ALTER TABLE public.psp_access_area_settings
    ADD CONSTRAINT chk_psp_access_area_key
    CHECK (
        area_key IN (
            'employees_compensation',
            'employee_management',
            'financial_management',
            'add_income',
            'add_expense',
            'business_goals',
            'business_users',
            'business_security'
        )
    );

-- Initialize Employee Management for existing workspaces.
-- Level 1 is the most restrictive access level.
-- Existing settings are never overwritten.

INSERT INTO public.psp_access_area_settings (
    spa_id,
    business_unit_id,
    area_key,
    required_access_level
)
SELECT
    bu.spa_id,
    bu.business_unit_id,
    'employee_management',
    1
FROM public.business_units bu
ON CONFLICT (
    spa_id,
    business_unit_id,
    area_key
)
DO NOTHING;

COMMIT;
