BEGIN;

-- PEACH SUITE PRO
-- Three independently Owner-configurable payroll Restricted Areas.
-- Existing area settings and employee assignments are preserved.
-- Initial Level 1 is a configurable default, not a fixed requirement.

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '90s';

DO $preflight$
DECLARE
    definition TEXT;
    existing_key TEXT;
BEGIN
    SELECT pg_get_constraintdef(c.oid)
    INTO definition
    FROM pg_constraint c
    WHERE c.conrelid =
        'public.psp_access_area_settings'::regclass
      AND c.conname = 'chk_psp_access_area_key'
      AND c.contype = 'c';

    IF definition IS NULL THEN
        RAISE EXCEPTION
            'STOP: Existing Restricted Area constraint missing.';
    END IF;

    FOREACH existing_key IN ARRAY ARRAY[
        'employee_management',
        'employees_compensation',
        'financial_management',
        'add_income',
        'add_expense',
        'business_goals',
        'business_users',
        'business_security'
    ]
    LOOP
        IF position(existing_key IN definition) = 0 THEN
            RAISE EXCEPTION
                'STOP: Unexpected existing area constraint: %',
                existing_key;
        END IF;
    END LOOP;

    IF position('hours_payroll' IN definition) > 0
       OR position('my_hours_pay' IN definition) > 0
       OR position('payroll_adjustments_reports' IN definition) > 0
    THEN
        RAISE EXCEPTION
            'STOP: Payroll Restricted Areas already in constraint.';
    END IF;
END;
$preflight$;

ALTER TABLE public.psp_access_area_settings
    DROP CONSTRAINT chk_psp_access_area_key;

ALTER TABLE public.psp_access_area_settings
    ADD CONSTRAINT chk_psp_access_area_key
    CHECK (
        area_key IN (
            'employee_management',
            'employees_compensation',
            'financial_management',
            'add_income',
            'add_expense',
            'business_goals',
            'business_users',
            'business_security',
            'hours_payroll',
            'my_hours_pay',
            'payroll_adjustments_reports'
        )
    );

-- Seed all existing workspaces without changing existing settings.
-- Owners may subsequently select any required level from 1 to 8.

INSERT INTO public.psp_access_area_settings (
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
FROM public.business_units bu
CROSS JOIN (
    VALUES
        ('hours_payroll'),
        ('my_hours_pay'),
        ('payroll_adjustments_reports')
) AS areas(area_key)
ON CONFLICT (spa_id, business_unit_id, area_key)
DO NOTHING;

-- Confirm every existing workspace has all three settings.

DO $verify$
DECLARE
    missing_count INTEGER;
BEGIN
    SELECT COUNT(*)
    INTO missing_count
    FROM public.business_units bu
    CROSS JOIN (
        VALUES
            ('hours_payroll'),
            ('my_hours_pay'),
            ('payroll_adjustments_reports')
    ) AS areas(area_key)
    LEFT JOIN public.psp_access_area_settings s
      ON s.spa_id = bu.spa_id
     AND s.business_unit_id = bu.business_unit_id
     AND s.area_key = areas.area_key
    WHERE s.psp_access_area_setting_id IS NULL;

    IF missing_count <> 0 THEN
        RAISE EXCEPTION
            'STOP: % payroll area settings are missing.',
            missing_count;
    END IF;
END;
$verify$;

COMMIT;
