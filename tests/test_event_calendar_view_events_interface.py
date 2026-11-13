"""EC-065-2C View Events GET interface safety and rendering contracts."""
import ast
import unittest
from datetime import date
from pathlib import Path
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text()
PAGE = (ROOT / "templates/event_view_events.html").read_text()
TREE = ast.parse(APP)
NODES = [
    n for n in TREE.body
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    and n.name == "peachpos_view_events"
]


def source():
    node = NODES[0]
    lines = APP.splitlines(keepends=True)
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    return "".join(lines[start - 1:node.end_lineno])


def render_page(*, event_name="Keller Fall Festival", next_date="Oct 5-8",
                archived=False, empty=False):
    content = PAGE.split("{% block content %}", 1)[1].rsplit("{% endblock %}", 1)[0]
    env = Environment(autoescape=True, undefined=StrictUndefined)
    template = env.from_string(content)
    events = [] if empty else [{
        "event_id": 21,
        "event_name": event_name,
        "start_date": date(2026, 10, 15),
        "end_date": date(2026, 10, 17),
        "venue_name": "Keller Park",
        "city": "Keller",
        "state": "TX",
        "contact_name": "Festival Coordinator",
        "next_date_display": next_date,
        "is_archived": archived,
    }]
    return template.render(
        events=events,
        has_more=False,
        page=1,
        start_date="",
        end_date="",
        status="",
        search="",
        archive_mode="active",
        event_csrf_token="test-csrf-token",
        url_for=lambda endpoint, **kwargs: "/" + endpoint,
    )


class ViewEventsRouteContract(unittest.TestCase):
    def test_exactly_one_view_route(self):
        self.assertEqual(len(NODES), 1)
        self.assertEqual(APP.count('@app.route("/events/view", methods=["GET"])'), 1)

    def test_authentication_subscription_workspace_guards(self):
        for expected in (
            "@login_required", "@spa_required",
            '@require_subscription_feature("event_calendar")',
            '@require_workspace_permission("can_manage_event_units")',
            'current_business_unit_membership_role_code()',
            '!= "organization_admin"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, source())

    def test_scope_from_authentication_not_querystring(self):
        self.assertIn('spa_id, workspace_id, _actor_id = _event_unit_scope()', source())
        self.assertIn('list_view_events(', source())
        self.assertIn('spa_id,', source())
        self.assertIn('workspace_id,', source())
        self.assertNotIn('request.args.get("spa_id")', source())
        self.assertNotIn('request.args.get("workspace_id")', source())

    def test_read_only_transaction(self):
        self.assertIn('cur.execute("SET TRANSACTION READ ONLY")', source())
        self.assertIn('conn.rollback()', source())
        self.assertIn('conn.close()', source())
        self.assertNotIn('conn.commit()', source())
        for forbidden in ('UPDATE ', 'DELETE FROM ', 'INSERT INTO ', 'CREATE TABLE '):
            self.assertNotIn(forbidden, source().upper())

    def test_response_not_cached(self):
        self.assertIn('"private, no-store"', source())
        self.assertIn('"nosniff"', source())

    def test_date_validation_and_400(self):
        self.assertIn('date.fromisoformat(raw)', source())
        self.assertIn('abort(400)', source())
        self.assertIn('start_date=parse_date', source().replace(' ', ''))

    def test_pagination_bound_and_page_size(self):
        self.assertIn('not 1 <= page <= 2001', source())
        self.assertIn('limit=50', source())
        self.assertIn('offset=(page - 1) * 50', source())

    def test_only_get_and_no_reminder_saving(self):
        self.assertIn('methods=["GET"]', source())
        self.assertNotIn('request.form', source())
        self.assertNotIn('save_business_schedule', source())

    def test_route_wires_existing_service(self):
        self.assertIn('services.event_calendar_view_events', source())
        self.assertIn('archive_mode=archive_mode', source())
        self.assertIn('start_date=start_date', source())
        self.assertIn('status=status', source())
        self.assertIn('search=search', source())


class ViewEventsPageContract(unittest.TestCase):
    def test_jinja_valid(self):
        Environment().parse(PAGE)

    def test_appointments_style_filters(self):
        for field in ('search', 'start_date', 'end_date', 'status', 'archive'):
            self.assertIn(f'name="{field}"', PAGE)

    def test_columns(self):
        for title in ('Date', 'Event', 'City', 'Contact Name', 'Next Occurrence', 'Actions'):
            self.assertIn(f'>{title}</th>', PAGE)

    def test_view_and_edit_links_exist(self):
        self.assertIn("url_for('peachpos_event_calendar_month'", PAGE)
        self.assertIn("url_for('event_new', edit=event.event_id)", PAGE)
        self.assertIn('>Go To Month</a>', PAGE)

    def test_only_supported_archive_post_forms(self):
        self.assertNotIn('Create Reminder</', PAGE)
        self.assertIn('method="POST"', PAGE)
        self.assertIn("url_for('peachpos_event_archive'", PAGE)
        self.assertIn("url_for('peachpos_event_restore'", PAGE)
        self.assertNotIn('fetch(', PAGE)
        self.assertNotIn('onclick=', PAGE)

    def test_render_event_once_and_exact_flexible_reference(self):
        result = render_page()
        self.assertEqual(result.count('Keller Fall Festival'), 1)
        self.assertEqual(result.count('Oct 5-8'), 1)
        self.assertIn('Keller, TX', result)
        self.assertIn('Festival Coordinator', result)
        self.assertIn('through Oct 17, 2026', result)

    def test_xss_escaped_in_event_and_next_date(self):
        result = render_page(event_name='<script>alert(1)</script>',
                             next_date='<img src=x onerror=alert(1)>')
        self.assertNotIn('<script>alert(1)</script>', result)
        self.assertNotIn('<img src=x onerror=alert(1)>', result)
        self.assertIn('&lt;script&gt;', result)
        self.assertIn('&lt;img', result)

    def test_archived_indicator_is_only_metadata(self):
        result = render_page(archived=True)
        self.assertIn('Archived reference', result)
        self.assertIn('Go To Month', result)
        self.assertIn('Edit', result)

    def test_empty_state(self):
        self.assertIn('No events match these filters.', render_page(empty=True))

    def test_reference_boundary_text(self):
        result = render_page()
        self.assertIn('Next Occurrence is a flexible planning reference only', result)
        self.assertIn('does not create an', result)
        self.assertIn('Business Schedule reminder', result)


if __name__ == "__main__":
    unittest.main()
