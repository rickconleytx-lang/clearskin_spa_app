BEGIN;

-- ==========================================================
-- PEACH SUITE PRO
-- PSP ACCESS LEVELS 1-8
--
-- Expand employee and Restricted Area access levels
-- from 1-5 to 1-8.
--
-- Preserve all existing assignments and settings.
-- Owner remains Level 1.
-- Employee Role Slots are NOT changed.
--
-- Additive, transactional migration.
-- ==========================================================

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '90s';

-- Verify the previously installed constraints before
-- replacing them. Unexpected schema state must stop
-- this migration rather than silently changing it.

DO $verify_existing$
DECLARE
    employee_rule TEXT;
    area_rule TEXT;
BEGIN
    SELECT pg_get_constraintdef(c.oid)
    INTO employee_rule
    FROM pg_constraint c
    WHERE c.conrelid =
        'public.employee_business_unit_memberships'::regclass
      AND c.conname =
        'chk_employee_business_unit_membership_access_level'
      AND c.contype = 'c';

    IF employee_rule IS NULL
       OR employee_rule NOT LIKE '%access_level IS NULL%'
       OR employee_rule NOT LIKE '%access_level >= 1%'
       OR employee_rule NOT LIKE '%access_level <= 5%'
    THEN
        RAISE EXCEPTION
            'STOP: Unexpected employee access-level constraint.';
    END IF;

    SELECT pg_get_constraintdef(c.oid)
    INTO area_rule
    FROM pg_constraint c
    WHERE c.conrelid =
        'public.psp_access_area_settings'::regclass
      AND c.conname =
        'chk_psp_access_area_required_level'
      AND c.contype = 'c';

    IF area_rule IS NULL
       OR area_rule NOT LIKE '%required_access_level >= 1%'
       OR area_rule NOT LIKE '%required_access_level <= 5%'
    THEN
        RAISE EXCEPTION
            'STOP: Unexpected Restricted Area level constraint.';
    END IF;
END;
$verify_existing$;

-- Employee access levels: NULL or Levels 1-8.

ALTER TABLE public.employee_business_unit_memberships
    DROP CONSTRAINT
        chk_employee_business_unit_membership_access_level;

ALTER TABLE public.employee_business_unit_memberships
    ADD CONSTRAINT
        chk_employee_business_unit_membership_access_level
    CHECK (
        access_level IS NULL
        OR access_level BETWEEN 1 AND 8
    );

-- Restricted Area requirements: Levels 1-8.

ALTER TABLE public.psp_access_area_settings
    DROP CONSTRAINT chk_psp_access_area_required_level;

ALTER TABLE public.psp_access_area_settings
    ADD CONSTRAINT chk_psp_access_area_required_level
    CHECK (
        required_access_level BETWEEN 1 AND 8
    );

-- Verify both replacement constraints before committing.

DO $verify_new$
DECLARE
    employee_rule TEXT;
    area_rule TEXT;
BEGIN
    SELECT pg_get_constraintdef(c.oid)
    INTO employee_rule
    FROM pg_constraint c
    WHERE c.conrelid =
        'public.employee_business_unit_memberships'::regclass
      AND c.conname =
        'chk_employee_business_unit_membership_access_level';

    SELECT pg_get_constraintdef(c.oid)
    INTO area_rule
    FROM pg_constraint c
    WHERE c.conrelid =
        'public.psp_access_area_settings'::regclass
      AND c.conname =
        'chk_psp_access_area_required_level';

    IF employee_rule IS NULL
       OR employee_rule NOT LIKE '%access_level <= 8%'
       OR area_rule IS NULL
       OR area_rule NOT LIKE '%required_access_level <= 8%'
    THEN
        RAISE EXCEPTION
            'STOP: Level 1-8 constraint verification failed.';
    END IF;
END;
$verify_new$;

COMMIT;
