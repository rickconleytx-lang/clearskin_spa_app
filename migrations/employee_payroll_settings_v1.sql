
BEGIN;

-- =====================================================
-- PEACH SUITE PRO
-- EMPLOYEE PAYROLL SETTINGS V1
--
-- Shared payroll configuration for all subscriptions.
-- Operational payroll restricted separately to
-- PeachPOS and Team.
--
-- Additive migration.
-- =====================================================

-- SAFETY:
-- Prototype rate table must be empty before adding
-- workspace-level ownership requirements.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.employee_pay_rates
        LIMIT 1
    ) THEN
        RAISE EXCEPTION
            'employee_pay_rates contains existing data; '
            'review records before applying migration';
    END IF;
END
$$;


-- =====================================================
-- 1. EMPLOYEE PAY RATES
-- =====================================================

ALTER TABLE public.employee_pay_rates
    ADD COLUMN business_unit_id INTEGER;

ALTER TABLE public.employee_pay_rates
    ALTER COLUMN business_unit_id SET NOT NULL;

-- Remove unsafe prototype tenant default.
ALTER TABLE public.employee_pay_rates
    ALTER COLUMN spa_id DROP DEFAULT;

-- Every rate belongs to a registered employee
-- membership in the specified workspace.
ALTER TABLE public.employee_pay_rates
    ADD CONSTRAINT fk_employee_pay_rates_membership
    FOREIGN KEY (
        spa_id,
        business_unit_id,
        employee_id
    )
    REFERENCES public.employee_business_unit_memberships (
        spa_id,
        business_unit_id,
        employee_id
    )
    ON DELETE RESTRICT;

-- Mixed compensation uses multiple rate rows.
ALTER TABLE public.employee_pay_rates
    ADD CONSTRAINT chk_employee_pay_rates_type
    CHECK (
        pay_type IN ('hourly', 'daily', 'event')
    );

ALTER TABLE public.employee_pay_rates
    ADD CONSTRAINT chk_employee_pay_rates_amount
    CHECK (rate >= 0);

ALTER TABLE public.employee_pay_rates
    ADD CONSTRAINT chk_employee_pay_rates_dates
    CHECK (
        end_date IS NULL
        OR end_date >= effective_date
    );

-- Prevent duplicate rates with identical
-- effective dates in the same workspace.
CREATE UNIQUE INDEX
    uq_employee_pay_rates_effective
ON public.employee_pay_rates (
    spa_id,
    business_unit_id,
    employee_id,
    pay_type,
    effective_date
);


-- =====================================================
-- 2. EMPLOYEE PAYROLL SETTINGS
-- =====================================================

CREATE TABLE public.employee_payroll_settings (
    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,

    default_pay_period VARCHAR(20),

    fica_withholding_percent NUMERIC(5,2),

    deduction_1_title VARCHAR(100),
    deduction_1_amount NUMERIC(12,2),

    deduction_2_title VARCHAR(100),
    deduction_2_amount NUMERIC(12,2),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_employee_payroll_settings
        PRIMARY KEY (
            spa_id,
            business_unit_id,
            employee_id
        ),

    CONSTRAINT fk_employee_payroll_settings_membership
        FOREIGN KEY (
            spa_id,
            business_unit_id,
            employee_id
        )
        REFERENCES public.employee_business_unit_memberships (
            spa_id,
            business_unit_id,
            employee_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT chk_employee_pay_period
        CHECK (
            default_pay_period IS NULL
            OR default_pay_period IN (
                'weekly',
                'biweekly',
                'semimonthly',
                'monthly'
            )
        ),

    CONSTRAINT chk_employee_fica_percent
        CHECK (
            fica_withholding_percent IS NULL
            OR (
                fica_withholding_percent >= 0
                AND fica_withholding_percent <= 100
            )
        ),

    CONSTRAINT chk_employee_deduction_1
        CHECK (
            deduction_1_amount IS NULL
            OR deduction_1_amount >= 0
        ),

    CONSTRAINT chk_employee_deduction_2
        CHECK (
            deduction_2_amount IS NULL
            OR deduction_2_amount >= 0
        )
);

COMMENT ON TABLE public.employee_payroll_settings IS
    'Employee payroll configuration by PSP workspace. '
    'Settings are available to all subscriptions; '
    'operational payroll is restricted to PeachPOS and Team.';

COMMIT;
