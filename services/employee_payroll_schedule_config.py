"""
Peach Suite Pro - Payroll Schedule Configuration.

Validates company payroll schedule settings and provides
a pay-period preview.

No database writes.
"""

from dataclasses import dataclass
from datetime import date
import re

from services.employee_payroll_schedule import (
    calculate_pay_period,
)


class PayrollScheduleConfigError(ValueError):
    pass


@dataclass(frozen=True)
class CompanyPayrollSchedule:
    pay_frequency: str
    reference_start_date: date | None
    semimonthly_first_start_day: int | None
    semimonthly_second_start_day: int | None


SUPPORTED_FREQUENCIES = frozenset({
    "daily",
    "weekly",
    "biweekly",
    "semimonthly",
    "monthly",
})


def _optional_text(value):
    return str(value or "").strip()


def _parse_start_date(value):
    text = _optional_text(value)

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise PayrollScheduleConfigError(
            "A valid starting date is required."
        )

    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise PayrollScheduleConfigError(
            "Invalid payroll starting date."
        ) from exc


def _parse_start_day(value, label):
    text = _optional_text(value)

    if not re.fullmatch(r"\d{1,2}", text):
        raise PayrollScheduleConfigError(
            f"{label} must be a valid day of month."
        )

    return int(text)


def validate_company_payroll_schedule(form):
    """
    Validate Owner-entered company payroll schedule.

    Does not guess missing values.
    Does not create payroll periods.
    """

    frequency = _optional_text(
        form.get("pay_frequency")
    ).lower()

    if frequency not in SUPPORTED_FREQUENCIES:
        raise PayrollScheduleConfigError(
            "Select a valid payroll frequency."
        )

    reference_text = _optional_text(
        form.get("reference_start_date")
    )

    first_text = _optional_text(
        form.get("semimonthly_first_start_day")
    )

    second_text = _optional_text(
        form.get("semimonthly_second_start_day")
    )

    if frequency == "semimonthly":
        if reference_text:
            raise PayrollScheduleConfigError(
                "Semimonthly schedules use two "
                "monthly starting days."
            )

        first = _parse_start_day(
            first_text,
            "First semimonthly starting day",
        )

        second = _parse_start_day(
            second_text,
            "Second semimonthly starting day",
        )

        if not (1 <= first <= 27):
            raise PayrollScheduleConfigError(
                "First starting day must be 1 through 27."
            )

        if not (first < second <= 31):
            raise PayrollScheduleConfigError(
                "Second starting day must be later "
                "than the first and no greater than 31."
            )

        return CompanyPayrollSchedule(
            pay_frequency=frequency,
            reference_start_date=None,
            semimonthly_first_start_day=first,
            semimonthly_second_start_day=second,
        )

    if first_text or second_text:
        raise PayrollScheduleConfigError(
            "Monthly cutoff days are only used "
            "for semimonthly payroll."
        )

    return CompanyPayrollSchedule(
        pay_frequency=frequency,
        reference_start_date=_parse_start_date(
            reference_text
        ),
        semimonthly_first_start_day=None,
        semimonthly_second_start_day=None,
    )


def preview_company_pay_period(schedule, as_of):
    """Preview a period without creating a payroll record."""

    return calculate_pay_period(
        pay_frequency=schedule.pay_frequency,
        as_of=as_of,
        reference_start_date=schedule.reference_start_date,
        semimonthly_first_start_day=(
            schedule.semimonthly_first_start_day
        ),
        semimonthly_second_start_day=(
            schedule.semimonthly_second_start_day
        ),
    )
