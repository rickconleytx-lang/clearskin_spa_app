"""EC-064-2B: protected Year Calendar route and two-way Year/Month interface."""
import ast
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from jinja2 import DictLoader, Environment, select_autoescape
from services.event_calendar_year import build_year_view

ROOT = Path(__file__).resolve().parents[1]
MONTH = (ROOT / 'templates/event_calendar_month.html').read_text()
YEAR = (ROOT / 'templates/event_calendar_year.html').read_text()
SOURCE = (ROOT / 'app.py').read_text()

START = SOURCE.index('@app.route("/events/calendar/year", methods=["GET"])')
END = SOURCE.index('@app.route("/events/<int:event_id>/details", methods=["GET"])', START)
ROUTE = SOURCE[START:END]


def url_for(endpoint, **kw):
    paths = {
        'peachpos_event_calendar_year': '/events/calendar/year',
        'peachpos_event_calendar_week': '/events/calendar/week',
        'peachpos_event_calendar_month': '/events/calendar',
        'event_new': '/events/new',
        'event_units_home': '/events/units',
        'peachpos_view_events': '/events/view',
    }
    path = paths[endpoint]
    return path + ('?' + urlencode(kw) if kw else '')


def render(rows=None, year=2026, today=date(2026, 11, 11)):
    view = build_year_view(rows or [], year, today)
    environment = Environment(
        loader=DictLoader({
            'base.html': '{% block content %}{% endblock %}',
            'event_calendar_year.html': YEAR,
        }),
        autoescape=select_autoescape(['html']),
    )
    return environment.get_template('event_calendar_year.html').render(
        calendar=view, current_month=today.month if today.year == year else 1,
        url_for=url_for,
    )


class YearRouteContract(unittest.TestCase):
    def test_route_is_get_only(self):
        self.assertIn('@app.route("/events/calendar/year", methods=["GET"])', ROUTE)

    def test_all_month_equivalent_decorators(self):
        for expected in (
            '@login_required', '@spa_required',
            '@require_subscription_feature("event_calendar")',
            '@require_workspace_permission("can_manage_event_units")',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, ROUTE)

    def test_admin_role_gate(self):
        self.assertIn('current_business_unit_membership_role_code()', ROUTE)
        self.assertIn('!= "organization_admin"', ROUTE)
        self.assertIn('abort(403)', ROUTE)

    def test_rejects_invalid_year(self):
        self.assertIn('int(request.args["year"])', ROUTE)
        self.assertIn('except (ValueError, TypeError):', ROUTE)
        self.assertIn('not 2000 <= year <= 2100', ROUTE)
        self.assertIn('abort(400)', ROUTE)

    def test_workspace_is_authenticated(self):
        self.assertIn('spa_id, workspace_id, _actor_id = _event_unit_scope()', ROUTE)
        self.assertIn('conn, spa_id, workspace_id, year', ROUTE)

    def test_read_only_database_and_cleanup(self):
        self.assertIn('cur.execute("SET TRANSACTION READ ONLY")', ROUTE)
        self.assertIn('conn.rollback()', ROUTE)
        self.assertIn('conn.close()', ROUTE)
        self.assertNotIn('conn.commit()', ROUTE)

    def test_annual_aggregate_instead_of_month_detail_reader(self):
        self.assertIn('list_year_day_summaries(', ROUTE)
        self.assertIn('build_year_view(', ROUTE)
        self.assertNotIn('list_event_calendar_rows(', ROUTE)

    def test_no_store_response(self):
        self.assertIn('"Cache-Control"] = "private, no-store"', ROUTE)
        self.assertIn('"X-Content-Type-Options"] = "nosniff"', ROUTE)

    def test_route_syntax_is_valid(self):
        ast.parse(ROUTE)


class YearMonthInterfaceContract(unittest.TestCase):
    def test_existing_month_has_year_switch_and_active_month(self):
        self.assertIn("url_for('peachpos_event_calendar_year', year=calendar.year, show_archived=1 if show_archived else None)", MONTH)
        self.assertIn('aria-label="Event calendar views"', MONTH)
        self.assertIn('aria-current="page"', MONTH)
        self.assertIn('>Month</a>', MONTH)

    def test_month_details_and_quick_add_preserved(self):
        for needle in (
            'id="ec-detail-dialog"',
            'id="ec-detail-edit"',
            'id="ec-detail-copy"',
            "url_for('event_new', date=day.date.isoformat())",
            'data-details-url=',
            '".ec-month-event[data-details-url]"',
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, MONTH)

    def test_year_template_compiles(self):
        Environment().parse(YEAR)

    def test_twelve_months_render_and_link(self):
        html = render()
        self.assertEqual(html.count('<section class="ec-year-month"'), 12)
        for name in ('January', 'February', 'March', 'April', 'May', 'June',
                     'July', 'August', 'September', 'October', 'November', 'December'):
            with self.subTest(name=name):
                self.assertIn(name, html)
        self.assertIn('/events/calendar?year=2026&amp;month=12', html)

    def test_active_day_shows_one_event_three_units(self):
        html = render([{'date': date(2026, 12, 5), 'events': 1,
                        'units': 3, 'cancelled': 0}])
        self.assertIn('December 05, 2026: 1 event(s), 3 unit(s)', html)
        self.assertIn('1 active operating date(s)', html)
        self.assertIn('1 event-day(s)', html)
        self.assertIn('3 truck/unit-day(s)', html)

    def test_cancellation_only_date_does_not_show_active_marker(self):
        html = render([{'date': date(2026, 3, 4), 'events': 0,
                        'units': 0, 'cancelled': 1}])
        self.assertIn('March 04, 2026: 1 cancelled event(s)', html)
        self.assertIn('ec-year-date is-cancelled', html)
        self.assertNotIn('ec-year-date is-active', html)

    def test_previous_next_year_and_boundary_controls(self):
        middle = render()
        self.assertIn('/events/calendar/year?year=2025', middle)
        self.assertIn('/events/calendar/year?year=2027', middle)
        self.assertIn('This Year', middle)
        early = render(year=2000)
        self.assertIn('aria-disabled="true">Previous Year', early)
        late = render(year=2100)
        self.assertIn('aria-disabled="true">Next Year', late)

    def test_year_month_switch_and_actions(self):
        html = render()
        self.assertIn('aria-label="Event calendar views"', html)
        self.assertIn('aria-current="page"', html)
        self.assertIn('/events/calendar?year=2026&amp;month=11', html)
        self.assertIn('Add Event', html)
        self.assertIn('Manage Event Units', html)

    def test_year_view_does_not_show_private_event_details(self):
        for forbidden in ('employee_name', 'contact_phone', 'street_address',
                          'data-details-url', 'fetch(', '<form method="POST"'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, YEAR)

    def test_no_calendar_data_writes_in_ui(self):
        for forbidden in ('fetch(', 'XMLHttpRequest', 'window.location.assign(',
                          'save_peachpos_event', 'update_peachpos_event'):
            self.assertNotIn(forbidden, YEAR)


if __name__ == '__main__':
    unittest.main()
