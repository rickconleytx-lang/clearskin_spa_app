"""
Peach Suite Pro - Payroll Schedule Calculator.

Pure date calculations only.
No database operations or payroll record creation.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class PayPeriodWindow:
    start: date
    end: date


def _month_date(year, month, day):
    last_day = monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _shift_month(year, month, offset):
    index = year * 12 + month - 1 + offset
    new_year, new_month = divmod(index, 12)
    return new_year, new_month + 1


def calculate_pay_period(
    *,
    pay_frequency,
    as_of,
    reference_start_date=None,
    semimonthly_first_start_day=None,
    semimonthly_second_start_day=None,
):
    """
    Return the pay period containing as_of.

    Fixed cycles use an Owner-confirmed anchor date.
    Monthly cycles use the anchor's day of month.
    Semimonthly cycles use two configured start days.

    Period boundaries are inclusive.
    """

    if not isinstance(as_of, date):
        raise ValueError("A valid as_of date is required.")

    frequencies = {
        "daily",
        "weekly",
        "biweekly",
        "semimonthly",
        "monthly",
    }

    if pay_frequency not in frequencies:
        raise ValueError("Unsupported pay frequency.")

    if pay_frequency == "semimonthly":
        first = semimonthly_first_start_day
        second = semimonthly_second_start_day

        if (
            reference_start_date is not None
            or not isinstance(first, int)
            or not isinstance(second, int)
            or not (1 <= first <= 27)
            or not (first < second <= 31)
        ):
            raise ValueError(
                "Valid semimonthly start days are required."
            )

        y, m = as_of.year, as_of.month

        first_date = _month_date(y, m, first)
        second_date = _month_date(y, m, second)

        if as_of >= second_date:
            start = second_date
            ny, nm = _shift_month(y, m, 1)
            next_start = _month_date(ny, nm, first)

        elif as_of >= first_date:
            start = first_date
            next_start = second_date

        else:
            py, pm = _shift_month(y, m, -1)
            start = _month_date(py, pm, second)
            next_start = first_date

        return PayPeriodWindow(
            start=start,
            end=next_start - timedelta(days=1),
        )

    if not isinstance(reference_start_date, date):
        raise ValueError(
            "A reference pay period starting date is required."
        )

    if pay_frequency in ("daily", "weekly", "biweekly"):
        length = {
            "daily": 1,
            "weekly": 7,
            "biweekly": 14,
        }[pay_frequency]

        elapsed = (as_of - reference_start_date).days
        period_index = elapsed // length

        start = (
            reference_start_date
            + timedelta(days=period_index * length)
        )

        return PayPeriodWindow(
            start=start,
            end=start + timedelta(days=length - 1),
        )

    # Monthly: preserve the selected day of month,
    # clamping to the last day in shorter months.

    anchor_day = reference_start_date.day
    y, m = as_of.year, as_of.month

    start = _month_date(y, m, anchor_day)

    if as_of < start:
        y, m = _shift_month(y, m, -1)
        start = _month_date(y, m, anchor_day)

    ny, nm = _shift_month(y, m, 1)
    next_start = _month_date(ny, nm, anchor_day)

    return PayPeriodWindow(
        start=start,
        end=next_start - timedelta(days=1),
    )
