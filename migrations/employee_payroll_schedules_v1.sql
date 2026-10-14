BEGIN;

-- ==========================================================
-- PEACH SUITE PRO
-- EMPLOYEE PAYROLL SCHEDULES V1
--
-- Company default payroll schedule per workspace.
-- Employee-specific schedule overrides.
-- Preserve existing employee pay frequencies.
-- Add daily payroll frequency.
--
-- Additive migration.
-- ==========================================================

-- 1. Company default payroll schedule.

CREATE TABLE public.employee_payroll_company_schedules (
    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    pay_frequency VARCHAR(20) NOT NULL,

    reference_start_date DATE,

    semimonthly_first_start_day SMALLINT,
    semimonthly_second_start_day SMALLINT,

    created_by_user_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_by_user_id INTEGER,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_employee_payroll_company_schedules
        PRIMARY KEY (spa_id, business_unit_id),

    CONSTRAINT fk_payroll_company_schedule_workspace
        FOREIGN KEY (spa_id, business_unit_id)
        REFERENCES public.business_units(
            spa_id, business_unit_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_payroll_company_schedule_creator
        FOREIGN KEY (created_by_user_id)
        REFERENCES public.users(user_id),

    CONSTRAINT fk_payroll_company_schedule_updater
        FOREIGN KEY (updated_by_user_id)
        REFERENCES public.users(user_id),

    CONSTRAINT chk_payroll_company_frequency
        CHECK (
            pay_frequency IN (
                'daily',
                'weekly',
                'biweekly',
                'semimonthly',
                'monthly'
            )
        ),

    CONSTRAINT chk_payroll_company_schedule_dates
        CHECK (
            (
                pay_frequency = 'semimonthly'
                AND reference_start_date IS NULL
                AND semimonthly_first_start_day
                    BETWEEN 1 AND 27
                AND semimonthly_second_start_day
                    BETWEEN 2 AND 31
                AND semimonthly_second_start_day >
                    semimonthly_first_start_day
            )
            OR
            (
                pay_frequency <> 'semimonthly'
                AND reference_start_date IS NOT NULL
                AND semimonthly_first_start_day IS NULL
                AND semimonthly_second_start_day IS NULL
            )
        )
);

-- 2. Extend existing employee payroll settings.

ALTER TABLE public.employee_payroll_settings
    ADD COLUMN schedule_source VARCHAR(20)
        NOT NULL DEFAULT 'company',
    ADD COLUMN pay_period_anchor_date DATE,
    ADD COLUMN semimonthly_first_start_day SMALLINT,
    ADD COLUMN semimonthly_second_start_day SMALLINT;

-- 3. Preserve existing employee-specific frequencies.
-- Employees without a frequency inherit the company default.
-- Existing frequencies remain unchanged.

UPDATE public.employee_payroll_settings
SET schedule_source = 'employee'
WHERE default_pay_period IS NOT NULL;

ALTER TABLE public.employee_payroll_settings
    ADD CONSTRAINT chk_employee_payroll_schedule_source
    CHECK (
        schedule_source IN ('company', 'employee')
    );

ALTER TABLE public.employee_payroll_settings
    ADD CONSTRAINT chk_employee_payroll_semi_days
    CHECK (
        (
            semimonthly_first_start_day IS NULL
            AND semimonthly_second_start_day IS NULL
        )
        OR
        (
            semimonthly_first_start_day BETWEEN 1 AND 27
            AND semimonthly_second_start_day BETWEEN 2 AND 31
            AND semimonthly_second_start_day >
                semimonthly_first_start_day
        )
    );

-- 4. Support Daily in employee pay-frequency choices.

ALTER TABLE public.employee_payroll_settings
    DROP CONSTRAINT chk_employee_pay_period;

ALTER TABLE public.employee_payroll_settings
    ADD CONSTRAINT chk_employee_pay_period
    CHECK (
        default_pay_period IS NULL
        OR default_pay_period IN (
            'daily',
            'weekly',
            'biweekly',
            'semimonthly',
            'monthly'
        )
    );

-- 5. Support Daily in actual saved pay periods.

ALTER TABLE public.employee_payroll_periods
    DROP CONSTRAINT chk_payroll_period_frequency;

ALTER TABLE public.employee_payroll_periods
    ADD CONSTRAINT chk_payroll_period_frequency
    CHECK (
        pay_frequency_snapshot IN (
            'daily',
            'weekly',
            'biweekly',
            'semimonthly',
            'monthly'
        )
    );

COMMIT;
