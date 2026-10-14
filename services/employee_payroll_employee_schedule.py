
"""
Peach Suite Pro - Employee Payroll Schedule Resolution.

Company default or explicit employee override.
No database writes. No payroll period creation.
"""

from dataclasses import dataclass
from datetime import date

from services.employee_payroll_schedule_config import (
    PayrollScheduleConfigError,
    validate_company_payroll_schedule,
)


@dataclass(frozen=True)
class EmployeeScheduleChoice:
    schedule_source: str
    pay_frequency: str | None
    pay_period_anchor_date: date | None
    semimonthly_first_start_day: int | None
    semimonthly_second_start_day: int | None


def _text(value):
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "").strip()


def validate_employee_schedule_choice(form):
    """Validate the Owner's selected employee schedule."""

    source = _text(form.get("schedule_source")).lower()

    if source not in ("company", "employee"):
        raise PayrollScheduleConfigError(
            "Select Company Schedule or Employee Schedule."
        )

    fields = (
        "pay_frequency",
        "reference_start_date",
        "semimonthly_first_start_day",
        "semimonthly_second_start_day",
    )

    if source == "company":
        if any(_text(form.get(field)) for field in fields):
            raise PayrollScheduleConfigError(
                "Company Schedule cannot contain "
                "employee-specific schedule values."
            )

        return EmployeeScheduleChoice(
            schedule_source="company",
            pay_frequency=None,
            pay_period_anchor_date=None,
            semimonthly_first_start_day=None,
            semimonthly_second_start_day=None,
        )

    validated = validate_company_payroll_schedule(form)

    return EmployeeScheduleChoice(
        schedule_source="employee",
        pay_frequency=validated.pay_frequency,
        pay_period_anchor_date=validated.reference_start_date,
        semimonthly_first_start_day=(
            validated.semimonthly_first_start_day
        ),
        semimonthly_second_start_day=(
            validated.semimonthly_second_start_day
        ),
    )


def resolve_employee_schedule(
    *,
    company_row,
    employee_row,
):
    """
    Return (schedule_source, effective_schedule).

    Never invent missing dates or frequency settings.
    """

    employee_row = employee_row or {}

    source = (
        employee_row.get("schedule_source") or "company"
    )

    if source == "company":
        if company_row is None:
            raise PayrollScheduleConfigError(
                "Company payroll schedule is not configured."
            )

        row = company_row

        form = {
            "pay_frequency": row.get("pay_frequency"),
            "reference_start_date": _text(
                row.get("reference_start_date")
            ),
            "semimonthly_first_start_day": _text(
                row.get("semimonthly_first_start_day")
            ),
            "semimonthly_second_start_day": _text(
                row.get("semimonthly_second_start_day")
            ),
        }

    elif source == "employee":
        form = {
            "pay_frequency": employee_row.get(
                "default_pay_period"
            ),
            "reference_start_date": _text(
                employee_row.get("pay_period_anchor_date")
            ),
            "semimonthly_first_start_day": _text(
                employee_row.get(
                    "semimonthly_first_start_day"
                )
            ),
            "semimonthly_second_start_day": _text(
                employee_row.get(
                    "semimonthly_second_start_day"
                )
            ),
        }

    else:
        raise PayrollScheduleConfigError(
            "Invalid employee payroll schedule source."
        )

    try:
        schedule = validate_company_payroll_schedule(form)
    except PayrollScheduleConfigError as exc:
        raise PayrollScheduleConfigError(
            "Effective payroll schedule is incomplete "
            "or invalid: " + str(exc)
        ) from exc

    return source, schedule
