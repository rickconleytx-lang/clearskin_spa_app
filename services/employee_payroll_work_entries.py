"""Employee work-entry validation and persistence.

Separate from legacy Employee Compensation.
The caller controls transaction, authorization and audit logging.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from services.employee_payroll_settings import (
    PayrollSettingsValidationError,
    parse_payroll_decimal,
)


class PayrollWorkEntryError(ValueError):
    pass


class DuplicatePayrollWorkEntryError(PayrollWorkEntryError):
    pass


ZERO = Decimal("0.00")
MONEY_MAX = Decimal("9999999999.99")


def _number(form, field, maximum):
    try:
        return parse_payroll_decimal(
            form.get(field),
            field.replace("_", " ").title(),
            maximum,
        )
    except PayrollSettingsValidationError as exc:
        raise PayrollWorkEntryError(str(exc)) from exc


def validate_payroll_work_entry(form):
    """Validate one manually entered hourly, daily, or event entry."""

    raw_id = str(form.get("employee_id") or "").strip()

    if not raw_id.isdecimal():
        raise PayrollWorkEntryError("Select a valid employee.")

    employee_id = int(raw_id)

    if not 0 < employee_id <= 2147483647:
        raise PayrollWorkEntryError("Invalid employee ID.")

    try:
        work_date = date.fromisoformat(
            str(form.get("work_date") or "").strip()
        )
    except ValueError as exc:
        raise PayrollWorkEntryError(
            "A valid work date is required."
        ) from exc

    entry_type = str(
        form.get("entry_type") or ""
    ).strip().lower()

    if entry_type not in {"hourly", "daily", "event"}:
        raise PayrollWorkEntryError("Invalid work entry type.")

    try:
        request_id = str(
            UUID(str(form.get("entry_request_id") or "").strip())
        )
    except ValueError as exc:
        raise PayrollWorkEntryError(
            "Work entry request expired. Reload the form."
        ) from exc

    regular = _number(
        form, "regular_hours", Decimal("999999.99")
    ) or ZERO

    overtime = _number(
        form, "overtime_hours", Decimal("999999.99")
    ) or ZERO

    days = _number(
        form, "days_worked", Decimal("9999.99")
    ) or ZERO

    overtime_rate = _number(
        form, "overtime_rate", MONEY_MAX
    )

    event_rate = _number(
        form, "event_rate", MONEY_MAX
    )

    event_name = str(
        form.get("event_name") or ""
    ).strip()

    if len(event_name) > 200:
        raise PayrollWorkEntryError(
            "Event name cannot exceed 200 characters."
        )

    notes = str(form.get("notes") or "").strip()

    if len(notes) > 4000:
        raise PayrollWorkEntryError(
            "Notes cannot exceed 4000 characters."
        )

    if entry_type == "hourly":
        if regular + overtime <= ZERO:
            raise PayrollWorkEntryError(
                "Enter regular or overtime hours."
            )

        if days != ZERO or event_name or event_rate is not None:
            raise PayrollWorkEntryError(
                "Hourly entries cannot contain daily or event pay."
            )

        if overtime > ZERO:
            if overtime_rate is None or overtime_rate <= ZERO:
                raise PayrollWorkEntryError(
                    "An explicit positive overtime rate is required."
                )
        elif overtime_rate is not None:
            raise PayrollWorkEntryError(
                "An overtime rate requires overtime hours."
            )

    elif entry_type == "daily":
        if days <= ZERO:
            raise PayrollWorkEntryError(
                "Days worked must be greater than zero."
            )

        if (
            regular != ZERO or overtime != ZERO
            or overtime_rate is not None
            or event_name or event_rate is not None
        ):
            raise PayrollWorkEntryError(
                "Daily entries cannot contain hours or event pay."
            )

    else:
        if not event_name:
            raise PayrollWorkEntryError(
                "An event name is required."
            )

        if (
            regular != ZERO or overtime != ZERO
            or days != ZERO or overtime_rate is not None
        ):
            raise PayrollWorkEntryError(
                "Event entries cannot contain hours or daily pay."
            )

    return {
        "employee_id": employee_id,
        "work_date": work_date,
        "entry_type": entry_type,
        "regular_hours": regular,
        "overtime_hours": overtime,
        "days_worked": days,
        "overtime_rate": overtime_rate,
        "event_rate": event_rate,
        "event_name": event_name or None,
        "notes": notes or None,
        "entry_request_id": request_id,
    }


def create_payroll_work_entry(
    cur,
    *,
    spa_id,
    business_unit_id,
    user_id,
    entry,
):
    """Insert an authorized work entry with a historical rate snapshot.

    Caller must enforce subscription, workspace permission,
    Employee Verification, CSRF and audit requirements.
    Caller commits or rolls back the transaction.
    """

    employee_id = entry["employee_id"]
    work_date = entry["work_date"]
    entry_type = entry["entry_type"]

    # Lock active membership to coordinate with rate changes.
    cur.execute("""
        SELECT 1
        FROM employee_business_unit_memberships m
        JOIN employees e
          ON e.spa_id = m.spa_id
         AND e.employee_id = m.employee_id
        WHERE m.spa_id = %s
          AND m.business_unit_id = %s
          AND m.employee_id = %s
          AND m.is_active = TRUE
          AND e.is_active = TRUE
        FOR SHARE OF m
    """, (spa_id, business_unit_id, employee_id))

    if not cur.fetchone():
        raise PermissionError(
            "Employee is not active in this workspace."
        )

    # A unique request ID prevents accidental double submission.
    cur.execute("""
        SELECT work_entry_id
        FROM employee_payroll_work_entries
        WHERE spa_id = %s
          AND business_unit_id = %s
          AND source_system = 'manual'
          AND source_reference = %s
    """, (
        spa_id,
        business_unit_id,
        entry["entry_request_id"],
    ))

    if cur.fetchone():
        raise DuplicatePayrollWorkEntryError(
            "This work entry was already submitted."
        )

    cur.execute("""
        SELECT rate
        FROM employee_pay_rates
        WHERE spa_id = %s
          AND business_unit_id = %s
          AND employee_id = %s
          AND pay_type = %s
          AND effective_date <= %s
          AND (end_date IS NULL OR end_date >= %s)
        ORDER BY effective_date DESC, pay_rate_id DESC
        LIMIT 1
    """, (
        spa_id,
        business_unit_id,
        employee_id,
        entry_type,
        work_date,
        work_date,
    ))

    rate_row = cur.fetchone()

    if entry_type == "event" and entry["event_rate"] is not None:
        rate = entry["event_rate"]
    elif rate_row:
        rate = (
            rate_row["rate"]
            if isinstance(rate_row, dict)
            else rate_row[0]
        )
    else:
        raise PayrollWorkEntryError(
            f"No {entry_type} pay rate is configured "
            "for the selected work date."
        )

    cur.execute("""
        INSERT INTO employee_payroll_work_entries (
            spa_id,
            business_unit_id,
            employee_id,
            work_date,
            entry_type,
            regular_hours,
            overtime_hours,
            days_worked,
            rate_snapshot,
            overtime_rate_snapshot,
            event_name_snapshot,
            notes,
            source_system,
            source_reference,
            created_by_user_id
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, 'manual', %s, %s
        )
        RETURNING work_entry_id
    """, (
        spa_id,
        business_unit_id,
        employee_id,
        work_date,
        entry_type,
        entry["regular_hours"],
        entry["overtime_hours"],
        entry["days_worked"],
        rate,
        entry["overtime_rate"]
        if entry_type == "hourly" else None,
        entry["event_name"]
        if entry_type == "event" else None,
        entry["notes"],
        entry["entry_request_id"],
        user_id,
    ))

    row = cur.fetchone()

    return (
        row["work_entry_id"]
        if isinstance(row, dict)
        else row[0]
    )
