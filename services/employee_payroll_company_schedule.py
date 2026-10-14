"""
Peach Suite Pro - Company Payroll Schedule Storage.

Workspace-scoped schedule retrieval and persistence.

The calling route is responsible for:
- Authentication and authorization.
- Employee Verification.
- CSRF validation.
- Transaction ownership.
- Audit logging.

No automatic payroll period creation.
"""

from services.employee_payroll_schedule_config import (
    CompanyPayrollSchedule,
    PayrollScheduleConfigError,
)


def get_company_payroll_schedule(
    cur,
    *,
    spa_id,
    business_unit_id,
):
    """Retrieve the saved default schedule for one workspace."""

    cur.execute("""
        SELECT
            spa_id,
            business_unit_id,
            pay_frequency,
            reference_start_date,
            semimonthly_first_start_day,
            semimonthly_second_start_day,
            created_at,
            updated_at
        FROM public.employee_payroll_company_schedules
        WHERE spa_id = %s
          AND business_unit_id = %s
    """, (
        spa_id,
        business_unit_id,
    ))

    row = cur.fetchone()
    return dict(row) if row is not None else None


def save_company_payroll_schedule(
    cur,
    *,
    spa_id,
    business_unit_id,
    actor_user_id,
    schedule,
):
    """
    Insert or update a company payroll schedule.

    Returns True when a database row changes.
    Returns False when the submitted settings are unchanged.

    Caller must supply the authenticated PSP user ID
    and manage commit/rollback and audit logging.
    """

    if not isinstance(schedule, CompanyPayrollSchedule):
        raise PayrollScheduleConfigError(
            "A validated payroll schedule is required."
        )

    if (
        not isinstance(actor_user_id, int)
        or isinstance(actor_user_id, bool)
        or actor_user_id <= 0
    ):
        raise ValueError(
            "An authenticated PSP user is required."
        )

    # Verify the target workspace exists.
    # Route-level authorization is still mandatory.

    cur.execute("""
        SELECT 1
        FROM public.business_units
        WHERE spa_id = %s
          AND business_unit_id = %s
        FOR SHARE
    """, (
        spa_id,
        business_unit_id,
    ))

    if cur.fetchone() is None:
        raise PermissionError(
            "Payroll workspace was not found."
        )

    cur.execute("""
        INSERT INTO public.employee_payroll_company_schedules (
            spa_id,
            business_unit_id,
            pay_frequency,
            reference_start_date,
            semimonthly_first_start_day,
            semimonthly_second_start_day,
            created_by_user_id
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (spa_id, business_unit_id)
        DO UPDATE SET
            pay_frequency = EXCLUDED.pay_frequency,
            reference_start_date =
                EXCLUDED.reference_start_date,
            semimonthly_first_start_day =
                EXCLUDED.semimonthly_first_start_day,
            semimonthly_second_start_day =
                EXCLUDED.semimonthly_second_start_day,
            updated_by_user_id = %s,
            updated_at = NOW()
        WHERE (
            employee_payroll_company_schedules.pay_frequency,
            employee_payroll_company_schedules.reference_start_date,
            employee_payroll_company_schedules.semimonthly_first_start_day,
            employee_payroll_company_schedules.semimonthly_second_start_day
        ) IS DISTINCT FROM (
            EXCLUDED.pay_frequency,
            EXCLUDED.reference_start_date,
            EXCLUDED.semimonthly_first_start_day,
            EXCLUDED.semimonthly_second_start_day
        )
        RETURNING spa_id
    """, (
        spa_id,
        business_unit_id,
        schedule.pay_frequency,
        schedule.reference_start_date,
        schedule.semimonthly_first_start_day,
        schedule.semimonthly_second_start_day,
        actor_user_id,
        actor_user_id,
    ))

    return cur.fetchone() is not None
