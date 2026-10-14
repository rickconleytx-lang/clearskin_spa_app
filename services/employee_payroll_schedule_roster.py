
"""
Peach Suite Pro — Payroll Schedule Employee Roster.

Returns employees eligible for new operational
payroll schedule configuration in one workspace.

Caller is responsible for Hours & Payroll authorization
and Employee Verification.
"""


def get_payroll_schedule_employee_roster(
    cur,
    *,
    spa_id,
    business_unit_id,
):
    """List eligible employees alphabetically."""

    cur.execute("""
        SELECT
            e.employee_id,
            e.first_name,
            e.last_name
        FROM public.employee_business_unit_memberships m
        JOIN public.employees e
          ON e.spa_id = m.spa_id
         AND e.employee_id = m.employee_id
        WHERE m.spa_id = %s
          AND m.business_unit_id = %s
          AND m.is_active = TRUE
          AND e.is_active = TRUE
          AND (
              e.termination_date IS NULL
              OR e.termination_date >= CURRENT_DATE
          )
        ORDER BY
            LOWER(COALESCE(e.last_name, '')),
            LOWER(COALESCE(e.first_name, '')),
            e.employee_id
    """, (
        spa_id,
        business_unit_id,
    ))

    return [
        dict(row)
        for row in cur.fetchall()
    ]
