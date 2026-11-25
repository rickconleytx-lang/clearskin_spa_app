"""EC-065-4F: preserve appointment menu and verify POS navigation."""
import unittest
from pathlib import Path
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


def source(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


class PeachPOSNavigationContract(unittest.TestCase):
    def test_appointment_menu_remains_non_pos_only(self):
        base = source('templates/base.html')
        self.assertIn('nav_access.can_view_calendar and navigation_subscription_tier_code != "pos"', base)
        self.assertEqual(base.count('{% include "partials/calendar_menu.html" %}'), 1)
        self.assertIn('Calendar & Appointments', source('templates/partials/calendar_menu.html'))

    def test_pos_menu_has_separate_entitlement_gate(self):
        base = source('templates/base.html')
        self.assertIn('navigation_subscription_tier_code == "pos"', base)
        self.assertIn('and "event_calendar" in subscription_entitlements', base)
        self.assertEqual(base.count('{% include "partials/peachpos_calendar_menu.html" %}'), 1)

    def test_pos_menu_uses_existing_navigation_controls(self):
        menu = source('templates/partials/peachpos_calendar_menu.html')
        self.assertIn('Calendar &amp; Events', menu)
        for anchor in ('onclick="toggleCalendarMenu()"', 'id="calendarMenuDropdown"',
                       'id="calendarViewsNestedMenu"', 'toggleNestedAppMenu(',
                       'closeNestedAppMenuById('):
            self.assertIn(anchor, menu)
        self.assertEqual(menu.count('id="calendarMenuDropdown"'), 1)

    def test_pos_calendar_has_exact_three_views_in_order(self):
        menu = source('templates/partials/peachpos_calendar_menu.html')
        endpoints = ('peachpos_event_calendar_week', 'peachpos_event_calendar_month',
                     'peachpos_event_calendar_year')
        positions = [menu.index("url_for('" + endpoint + "')") for endpoint in endpoints]
        self.assertEqual(positions, sorted(positions))
        for name in ('Week View', 'Month View', 'Year View'):
            self.assertIn(name, menu)
        self.assertNotIn('Day View', menu)

    def test_events_links_use_protected_existing_routes(self):
        menu = source('templates/partials/peachpos_calendar_menu.html')
        self.assertIn('>Events</div>', menu)
        self.assertIn("url_for('event_new')", menu)
        self.assertIn("url_for('peachpos_view_events')", menu)
        for forbidden in ('calendar_day_view', 'calendar_view', 'add_appointment',
                          'daily_schedule', 'appointments'):
            self.assertNotIn("url_for('" + forbidden + "')", menu)

    def test_view_events_action_added_to_all_three_calendars(self):
        for view in ('month', 'week', 'year'):
            with self.subTest(view=view):
                content = source('templates/event_calendar_' + view + '.html')
                self.assertEqual(content.count("url_for('peachpos_view_events')"), 1)
                self.assertLess(content.index("url_for('event_new')"),
                                content.index("url_for('peachpos_view_events')"))
                self.assertLess(content.index("url_for('peachpos_view_events')"),
                                content.index("url_for('event_units_home')"))

    def test_all_edited_templates_parse(self):
        env = Environment()
        for name in ('base.html', 'partials/peachpos_calendar_menu.html',
                     'event_calendar_month.html', 'event_calendar_week.html',
                     'event_calendar_year.html'):
            with self.subTest(name=name):
                env.parse(source('templates/' + name))

    def test_original_appointment_links_unchanged(self):
        menu = source('templates/partials/calendar_menu.html')
        for endpoint in ('calendar_day_view', 'calendar_view', 'calendar_month_view',
                         'calendar_year_view', 'daily_schedule', 'add_appointment',
                         'appointments'):
            self.assertIn("'" + endpoint + "'", menu)


if __name__ == '__main__':
    unittest.main()
