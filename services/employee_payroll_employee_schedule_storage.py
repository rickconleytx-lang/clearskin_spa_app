
"""
Peach Suite Pro — Employee Payroll Schedule Storage.

Workspace-scoped employee schedule persistence.

Caller must enforce:
- PSP authentication and workspace authorization
- Hours & Payroll Restricted Area
- Personal Employee Verification
- CSRF validation
- Audit logging and transaction commit/rollback

Does not calculate earnings or create payroll periods.
"""

from services.employee_payroll_employee_schedule import (
    EmployeeScheduleChoice,
)
from services.employee_payroll_schedule_config import (
    PayrollScheduleConfigError,
)


def get_employee_schedule_settings(
    cur,
    *,
    spa_id,
    business_unit_id,
    employee_id,
):
    """Read schedule settings for an active workspace employee."""

    cur.execute("""
        SELECT
            s.schedule_source,
            s.default_pay_period,
            s.pay_period_anchor_date,
            s.semimonthly_first_start_day,
            s.semimonthly_second_start_day
        FROM public.employee_payroll_settings s
        JOIN public.employee_business_unit_memberships m
          ON m.spa_id = s.spa_id
         AND m.business_unit_id = s.business_unit_id
         AND m.employee_id = s.employee_id
         AND m.is_active = TRUE
        WHERE s.spa_id = %s
          AND s.business_unit_id = %s
          AND s.employee_id = %s
    """, (
        spa_id,
        business_unit_id,
        employee_id,
    ))

    row = cur.fetchone()
    return dict(row) if row is not None else None


def save_employee_schedule_choice(
    cur,
    *,
    spa_id,
    business_unit_id,
    employee_id,
    choice,
):
    """
    Save one employee's operational payroll schedule.

    Does not modify withholding, deductions, or pay rates.
    Returns True if changed; False if unchanged.
    """

    if not isinstance(choice, EmployeeScheduleChoice):
        raise PayrollScheduleConfigError(
            "A validated employee schedule is required."
        )

    if choice.schedule_source not in ("company", "employee"):
        raise PayrollScheduleConfigError(
            "Invalid employee schedule source."
        )

    # Lock and verify the employee's active membership
    # within the exact PSP workspace.

    cur.execute("""
        SELECT 1
        FROM public.employee_business_unit_memberships m
        JOIN public.employees e
          ON e.spa_id = m.spa_id
         AND e.employee_id = m.employee_id
        WHERE m.spa_id = %s
          AND m.business_unit_id = %s
          AND m.employee_id = %s
          AND m.is_active = TRUE
          AND e.is_active = TRUE
          AND (
              e.termination_date IS NULL
              OR e.termination_date >= CURRENT_DATE
          )
        FOR SHARE OF m, e
    """, (
        spa_id,
        business_unit_id,
        employee_id,
    ))

    if cur.fetchone() is None:
        raise PermissionError(
            "Employee is not active in this workspace."
        )

    # An inherited schedule requires a configured
    # company payroll schedule.

    if choice.schedule_source == "company":
        if any(value is not None for value in (
            choice.pay_frequency,
            choice.pay_period_anchor_date,
            choice.semimonthly_first_start_day,
            choice.semimonthly_second_start_day,
        )):
            raise PayrollScheduleConfigError(
                "Company schedule cannot contain override values."
            )

        cur.execute("""
            SELECT 1
            FROM public.employee_payroll_company_schedules
            WHERE spa_id = %s
              AND business_unit_id = %s
            FOR SHARE
        """, (
            spa_id,
            business_unit_id,
        ))

        if cur.fetchone() is None:
            raise PayrollScheduleConfigError(
                "Configure the company payroll schedule first."
            )

    else:
        from services.employee_payroll_schedule_config import (
            validate_company_payroll_schedule,
        )

        validated = validate_company_payroll_schedule({
            "pay_frequency": choice.pay_frequency,
            "reference_start_date": (
                choice.pay_period_anchor_date.isoformat()
                if choice.pay_period_anchor_date else ""
            ),
            "semimonthly_first_start_day": (
                choice.semimonthly_first_start_day
            ),
            "semimonthly_second_start_day": (
                choice.semimonthly_second_start_day
            ),
        })

        if validated.pay_frequency != choice.pay_frequency:
            raise PayrollScheduleConfigError(
                "Employee schedule validation mismatch."
            )

    frequency = (
        choice.pay_frequency
        if choice.schedule_source == "employee"
        else None
    )

    cur.execute("""
        INSERT INTO public.employee_payroll_settings (
            spa_id,
            business_unit_id,
            employee_id,
            schedule_source,
            default_pay_period,
            pay_period_anchor_date,
            semimonthly_first_start_day,
            semimonthly_second_start_day,
            created_at,
            updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s,
            NOW(), NOW()
        )
        ON CONFLICT (
            spa_id,
            business_unit_id,
            employee_id
        )
        DO UPDATE SET
            schedule_source = EXCLUDED.schedule_source,
            default_pay_period = EXCLUDED.default_pay_period,
            pay_period_anchor_date =
                EXCLUDED.pay_period_anchor_date,
            semimonthly_first_start_day =
                EXCLUDED.semimonthly_first_start_day,
            semimonthly_second_start_day =
                EXCLUDED.semimonthly_second_start_day,
            updated_at = NOW()
        WHERE (
            employee_payroll_settings.schedule_source,
            employee_payroll_settings.default_pay_period,
            employee_payroll_settings.pay_period_anchor_date,
            employee_payroll_settings.semimonthly_first_start_day,
            employee_payroll_settings.semimonthly_second_start_day
        ) IS DISTINCT FROM (
            EXCLUDED.schedule_source,
            EXCLUDED.default_pay_period,
            EXCLUDED.pay_period_anchor_date,
            EXCLUDED.semimonthly_first_start_day,
            EXCLUDED.semimonthly_second_start_day
        )
        RETURNING employee_id
    """, (
        spa_id,
        business_unit_id,
        employee_id,
        choice.schedule_source,
        frequency,
        choice.pay_period_anchor_date,
        choice.semimonthly_first_start_day,
        choice.semimonthly_second_start_day,
    ))

    return cur.fetchone() is not None
