"""Pure Sunday-first Year Calendar model for PeachPOS Event Calendar."""
from calendar import Calendar, month_name
from datetime import date


class EventYearViewError(ValueError):
    """Invalid annual calendar presentation data."""


def build_year_view(summaries, year, today=None):
    """Build 12 month grids with operating-date activity indicators.

    Year totals are *event-days*, not distinct events: an event spanning four
    operating dates contributes four to its year's event-day total. A date with
    three trucks assigned to one event still contributes one event-day.
    The view is informational; clicking a month will open existing Month View.
    """
    if type(year) is not int or not 2000 <= year <= 2100:
        raise EventYearViewError("Invalid calendar year.")
    if today is None:
        today = date.today()
    if type(today) is not date:
        raise EventYearViewError("Invalid today date.")

    by_date = {}
    for item in summaries:
        if type(item) is not dict:
            raise EventYearViewError("Invalid annual summary.")
        day = item.get("date")
        if type(day) is not date or day.year != year or day in by_date:
            raise EventYearViewError("Invalid or duplicate annual date.")
        values = []
        for key in ("events", "units", "cancelled"):
            value = item.get(key)
            if type(value) is not int or value < 0:
                raise EventYearViewError("Invalid annual summary count.")
            values.append(value)
        by_date[day] = tuple(values)

    calendar = Calendar(firstweekday=6)
    months = []
    for number in range(1, 13):
        weeks = []
        month_dates = set()
        for week in calendar.monthdatescalendar(year, number):
            cells = []
            for day in week:
                in_month = day.month == number and day.year == year
                events, units, cancelled = (
                    by_date.get(day, (0, 0, 0)) if in_month else (0, 0, 0)
                )
                if in_month:
                    month_dates.add(day)
                cells.append({
                    "date": day,
                    "iso": day.isoformat(),
                    "number": day.day,
                    "in_month": in_month,
                    "today": day == today,
                    "events": events,
                    "units": units,
                    "cancelled": cancelled,
                    "has_activity": events > 0,
                })
            weeks.append(cells)
        months.append({
            "number": number,
            "name": month_name[number],
            "weeks": weeks,
            "active_dates": sum(
                by_date.get(day, (0, 0, 0))[0] > 0
                for day in month_dates
            ),
            "event_days": sum(
                by_date.get(day, (0, 0, 0))[0]
                for day in month_dates
            ),
            "unit_days": sum(
                by_date.get(day, (0, 0, 0))[1]
                for day in month_dates
            ),
            "cancelled_event_days": sum(
                by_date.get(day, (0, 0, 0))[2]
                for day in month_dates
            ),
        })

    return {
        "year": year,
        "label": str(year),
        "months": months,
        "active_dates": sum(m["active_dates"] for m in months),
        "event_days": sum(m["event_days"] for m in months),
        "unit_days": sum(m["unit_days"] for m in months),
        "cancelled_event_days": sum(
            m["cancelled_event_days"] for m in months
        ),
        "previous_year": year - 1 if year > 2000 else None,
        "next_year": year + 1 if year < 2100 else None,
    }
