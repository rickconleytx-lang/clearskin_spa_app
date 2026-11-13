"""EC-064-3B: protected Week endpoint and Year/Month/Week view integration.

Render with the actual weekly view model and the installed Jinja template.
No database operations or Flask app are required in these tests.
"""
import ast
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from jinja2 import DictLoader, Environment, select_autoescape
from services.event_calendar_week import build_week_view
from datetime import datetime, timezone


def sample(unit_id=1, **changes):
    row = {
        "event_id": 21,
        "event_name": "Food Truck Festival",
        "venue_name": "Downtown Square",
        "city": "Southlake", "state": "TX", "event_status": "scheduled",
        "timezone_name": "America/Chicago", "daily_schedule_id": 120,
        "operating_date": date(2026, 12, 5),
        "opens_at": datetime(2026, 12, 5, 16, tzinfo=timezone.utc),
        "closes_at": datetime(2026, 12, 5, 23, tzinfo=timezone.utc),
        "event_unit_id": unit_id, "unit_name": f"Truck {unit_id}",
        "calendar_color": "#00f900",
    }
    row.update(changes)
    return row

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text()
MONTH = (ROOT / "templates/event_calendar_month.html").read_text()
YEAR = (ROOT / "templates/event_calendar_year.html").read_text()
WEEK = (ROOT / "templates/event_calendar_week.html").read_text()
M_START = APP.index('@app.route("/events/calendar", methods=["GET"])')
W_START = APP.index('@app.route("/events/calendar/week", methods=["GET"])')
Y_START = APP.index('@app.route("/events/calendar/year", methods=["GET"])')
DETAILS_START = APP.index('@app.route("/events/<int:event_id>/details", methods=["GET"])')
WEEK_ROUTE = APP[W_START:Y_START]


def url_for(endpoint, **kw):
    paths = {
        "peachpos_event_calendar_year": "/events/calendar/year",
        "peachpos_event_calendar_month": "/events/calendar",
        "peachpos_event_calendar_week": "/events/calendar/week",
        "peachpos_event_calendar_details": "/events/21/details",
        "event_new": "/events/new",
        "event_units_home": "/events/units",
        "peachpos_view_events": "/events/view",
    }
    return paths[endpoint] + ("?" + urlencode(kw) if kw else "")


def render(rows=None, anchor=date(2026, 12, 5), today=date(2026, 12, 5)):
    model = build_week_view(rows or [], anchor, today)
    jinja = Environment(
        loader=DictLoader({
            "base.html": "{% block content %}{% endblock %}",
            "event_calendar_week.html": WEEK,
        }),
        autoescape=select_autoescape(["html"]),
    )
    return jinja.get_template("event_calendar_week.html").render(
        calendar=model, url_for=url_for, event_csrf_token="test-csrf-token"
    )


class WeekEndpointTests(unittest.TestCase):
    def test_route_is_get_only_and_lives_before_year(self):
        self.assertLess(M_START, W_START)
        self.assertLess(W_START, Y_START)
        self.assertLess(Y_START, DETAILS_START)
        self.assertIn('@app.route("/events/calendar/week", methods=["GET"])', WEEK_ROUTE)

    def test_route_has_all_access_guards(self):
        for marker in (
            "@login_required", "@spa_required",
            '@require_subscription_feature("event_calendar")',
            '@require_workspace_permission("can_manage_event_units")',
            'current_business_unit_membership_role_code() != "organization_admin"',
            "abort(403)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, WEEK_ROUTE)

    def test_date_and_month_parameters_validated(self):
        for marker in (
            'if "date" in args:',
            're.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value)',
            'date.fromisoformat(value)',
            'if "year" not in args or "month" not in args:',
            'int(args["year"])', 'int(args["month"])',
            'not 2000 <= year <= 2100', 'not 1 <= month <= 12',
            'not 2000 <= anchor.year <= 2100',
            'day = today.day if year == today.year and month == today.month else 1',
            'abort(400)',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, WEEK_ROUTE)

    def test_read_only_scoped_seven_day_reader(self):
        for marker in (
            '_event_unit_scope()', 'week_bounds(anchor)',
            'cur.execute("SET TRANSACTION READ ONLY")',
            'list_event_calendar_rows(',
            'conn, spa_id, workspace_id, week_start, week_end',
            'build_week_view(rows, anchor, today)',
            'conn.rollback()', 'conn.close()',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, WEEK_ROUTE)
        self.assertNotIn('conn.commit()', WEEK_ROUTE)

    def test_render_security_and_app_syntax(self):
        self.assertIn('"Cache-Control"] = "private, no-store"', WEEK_ROUTE)
        self.assertIn('"X-Content-Type-Options"] = "nosniff"', WEEK_ROUTE)
        self.assertIn('event_csrf_token=_security_form_csrf_token()', WEEK_ROUTE)
        self.assertIn('"event_calendar_week.html"', WEEK_ROUTE)
        ast.parse(WEEK_ROUTE)
        ast.parse(APP)


class WeekTemplateTests(unittest.TestCase):
    def test_render_seven_days_and_sunday_saturday_order(self):
        html = render()
        self.assertEqual(html.count('<section class="ec-week-day'), 7)
        self.assertLess(html.index('>Sun</span>'), html.index('>Sat</span>'))

    def test_all_three_switches_present_and_active(self):
        html = render()
        self.assertIn('aria-label="Event calendar views"', html)
        self.assertIn('/events/calendar/year?year=2026', html)
        self.assertIn('/events/calendar?year=2026&amp;month=12', html)
        self.assertIn('aria-current="page"', html)
        self.assertIn('>Week</a>', html)

    def test_prev_next_this_navigation(self):
        html = render(anchor=date(2026, 12, 5))
        self.assertIn('/events/calendar/week?date=2026-11-22', html)
        self.assertIn('/events/calendar/week?date=2026-12-06', html)
        self.assertIn('>This Week</a>', html)

    def test_cross_year_week_renders(self):
        html = render(anchor=date(2027, 1, 1))
        self.assertIn('December 27, 2026', html)
        self.assertIn('January 2, 2027', html)

    def test_one_event_three_trucks_renders_three_cards(self):
        rows = [sample(unit_id=i) for i in (1, 2, 3)]
        html = render(rows)
        self.assertEqual(html.count('class="ec-week-event"'), 3)
        self.assertIn('1 event-day(s)', html)
        self.assertIn('3 truck/unit-day assignment(s)', html)
        for i in (1, 2, 3):
            self.assertIn(f'Truck {i}', html)

    def test_event_cards_show_hours_venue_location(self):
        html = render([sample()])
        for marker in (
            'Food Truck Festival', '10:00 AM', '5:00 PM',
            'Downtown Square', 'Southlake, TX',
            'style="background-color: #00f900; color: #17212B;"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

    def test_cancelled_events_labeled(self):
        html = render([sample(event_status='cancelled')])
        self.assertIn('ec-week-event is-cancelled', html)
        self.assertIn('>Cancelled</span>', html)

    def test_empty_days_have_clear_message(self):
        html = render()
        self.assertEqual(html.count('No scheduled events'), 7)

    def test_date_number_opens_add_event(self):
        html = render()
        self.assertIn('/events/new?date=2026-12-05', html)
        self.assertIn('Add event on Saturday, December 05, 2026', html)

    def test_modal_includes_edit_copy_and_employee_details(self):
        for marker in (
            '<dialog id="ec-detail-dialog"',
            'id="ec-detail-edit"', 'id="ec-detail-copy"',
            'Employee Assignments',
            'id="ec-calendar-edit-csrf"',
            'cache: "no-store"',
            'credentials: "same-origin"',
            'document.querySelectorAll(',
            '".ec-week-event[data-details-url]"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, WEEK)
        self.assertNotIn('innerHTML', WEEK)

    def test_modal_button_targets_existing_details_endpoint(self):
        html = render([sample()])
        self.assertIn('data-details-url="/events/21/details?event_id=21"', html)
        self.assertIn('href="/events/new?date=2026-12-05"', html)

    def test_month_and_year_have_week_switch(self):
        for template in (MONTH, YEAR):
            self.assertIn('peachpos_event_calendar_week', template)
            self.assertIn('>Week</a>', template)
        self.assertIn("year=calendar.year, month=calendar.month", MONTH)
        self.assertIn("year=calendar.year, month=current_month", YEAR)

    def test_year_mock_url_for_supports_new_week_link(self):
        test = (ROOT / 'tests/test_event_calendar_year_interface.py').read_text()
        self.assertIn("'peachpos_event_calendar_week': '/events/calendar/week'", test)

    def test_no_event_data_writes(self):
        for forbidden in ('save_peachpos_event', 'update_peachpos_event',
                          'XMLHttpRequest', 'method: "POST"', 'innerHTML'):
            self.assertNotIn(forbidden, WEEK)
        self.assertNotIn('conn.commit()', WEEK_ROUTE)
        self.assertNotIn('@app.route("/events/calendar/week", methods=["POST"])', WEEK_ROUTE)

    def test_html_template_parses(self):
        Environment(loader=DictLoader({'base.html': '', 'event_calendar_week.html': WEEK})).parse(WEEK)
        self.assertIn('overflow-x: auto', WEEK)
        self.assertIn('min-width: 980px', WEEK)

    def test_year_2000_and_2100_disable_navigation(self):
        self.assertIn('aria-disabled="true">Previous Week', render(anchor=date(2000, 1, 1)))
        self.assertIn('aria-disabled="true">Next Week', render(anchor=date(2100, 12, 31)))

    def test_saved_event_text_is_html_escaped(self):
        html = render([sample(event_name='<script>alert(1)</script>')])
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)


if __name__ == '__main__':
    unittest.main()
