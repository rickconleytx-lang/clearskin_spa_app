"""Read-only pay-period navigation for Peach Suite Pro.

Uses the existing validated scheduling engine.
Never creates, approves, or pays payroll periods.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from services.employee_payroll_schedule import PayPeriodWindow
from services.employee_payroll_schedule_config import (
    preview_company_pay_period,
)


@dataclass(frozen=True)
class PayrollPeriodNavigation:
    current: PayPeriodWindow
    previous: PayPeriodWindow
    selected: PayPeriodWindow
    selected_previous: PayPeriodWindow
    selected_next: PayPeriodWindow
    selected_is_current: bool
    selected_is_previous: bool
    current_is_prestart: bool
    selected_is_prestart: bool
    first_scheduled: PayPeriodWindow | None


def build_pay_period_navigation(
    schedule,
    *,
    as_of,
    selected_date=None,
):
    """Return inclusive period windows without database changes."""

    if (
        not isinstance(as_of, date)
        or isinstance(as_of, datetime)
    ):
        raise ValueError("A valid as_of date is required.")

    if selected_date is None:
        selected_date = as_of

    if (
        not isinstance(selected_date, date)
        or isinstance(selected_date, datetime)
    ):
        raise ValueError(
            "A valid selected pay period date is required."
        )

    def period(day):
        return preview_company_pay_period(schedule, day)

    current = period(as_of)
    previous = period(
        current.start - timedelta(days=1)
    )

    selected = period(selected_date)

    selected_previous = period(
        selected.start - timedelta(days=1)
    )

    selected_next = period(
        selected.end + timedelta(days=1)
    )

    anchor = schedule.reference_start_date

    # Semimonthly schedules use day-of-month boundaries
    # and have no fixed reference starting date.
    current_is_prestart = (
        anchor is not None and as_of < anchor
    )

    selected_is_prestart = (
        anchor is not None and selected.start < anchor
    )

    first_scheduled = (
        period(anchor) if current_is_prestart else None
    )

    return PayrollPeriodNavigation(
        current=current,
        previous=previous,
        selected=selected,
        selected_previous=selected_previous,
        selected_next=selected_next,
        selected_is_current=selected == current,
        selected_is_previous=selected == previous,
        current_is_prestart=current_is_prestart,
        selected_is_prestart=selected_is_prestart,
        first_scheduled=first_scheduled,
    )


def build_pay_period_dropdown_options(
    schedule, *, as_of, selected_date=None, previous_count=12
):
    """Read-only dropdown choices, newest first."""
    if type(previous_count) is not int or not 1 <= previous_count <= 52:
        raise ValueError("Invalid previous period count.")

    state = build_pay_period_navigation(
        schedule, as_of=as_of, selected_date=selected_date
    )
    windows = [state.current]

    for _ in range(previous_count):
        if windows[-1].start == date.min:
            break
        windows.append(preview_company_pay_period(
            schedule, windows[-1].start - timedelta(days=1)
        ))

    if state.selected not in windows:
        windows.append(state.selected)

    windows.sort(key=lambda w: w.start, reverse=True)
    anchor = schedule.reference_start_date

    return [
        {
            "start": w.start,
            "end": w.end,
            "is_current": w == state.current,
            "is_selected": w == state.selected,
            "is_prestart": anchor is not None and w.start < anchor,
        }
        for w in windows
    ]
