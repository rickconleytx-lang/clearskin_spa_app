"""EC-065-4 Archive/Restore metadata reader and action safeguards."""
import ast
import unittest
from pathlib import Path
from datetime import date
from jinja2 import Environment, StrictUndefined
from services.event_calendar_view_events import (
    ViewEventsError, ViewEventsArchiveConflict, set_event_view_archived,
)

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text()
PAGE = (ROOT / "templates/event_view_events.html").read_text()
SERVICE = (ROOT / "services/event_calendar_view_events.py").read_text()
TREE = ast.parse(APP)


class Cursor:
    def __init__(self, row=(21,)):
        self.row = row
        self.calls = []
        self.closed = False
    def execute(self, sql, params):
        self.calls.append((sql, params))
    def fetchone(self):
        return self.row


class ArchiveRestoreTests(unittest.TestCase):
    def test_archive_uses_scoped_insert_upsert(self):
        cur = Cursor()
        self.assertTrue(set_event_view_archived(
            cur, spa_id=44, workspace_id=41, event_id=21,
            actor_id=9, archive=True,
        ))
        sql, params = cur.calls[0]
        self.assertEqual(params, (9, 44, 41, 21))
        self.assertIn("INSERT INTO public.event_calendar_view_metadata", sql)
        self.assertIn("FROM public.event_calendar_events", sql)
        self.assertIn("e.spa_id = %s", sql)
        self.assertIn("e.business_unit_id = %s", sql)
        self.assertIn("e.event_id = %s", sql)
        self.assertIn("archived_at IS NULL", sql)
        self.assertIn("ON CONFLICT (event_id)", sql)
        self.assertNotIn("next_date_reference =", sql)

    def test_restore_scoped_does_not_change_scheduled_event(self):
        cur = Cursor()
        self.assertFalse(set_event_view_archived(
            cur, spa_id=44, workspace_id=41, event_id=21,
            actor_id=9, archive=False,
        ))
        sql, params = cur.calls[0]
        self.assertEqual(params, (44, 41, 21))
        self.assertIn("UPDATE public.event_calendar_view_metadata", sql)
        self.assertIn("m.archived_at IS NOT NULL", sql)
        self.assertIn("FROM public.event_calendar_events", sql)
        self.assertIn("archived_by_user_id = NULL", sql)
        self.assertNotIn("UPDATE public.event_calendar_events", sql)
        self.assertNotIn("next_date_reference =", sql)

    def test_reject_invalid_scopes_and_mode(self):
        for values in ((0, 41, 21, 9), (44, 0, 21, 9),
                       (44, 41, 0, 9), (44, 41, 21, 0),
                       (True, 41, 21, 9), (44, "41", 21, 9)):
            with self.subTest(values=values), self.assertRaises(ViewEventsError):
                set_event_view_archived(Cursor(), spa_id=values[0],
                    workspace_id=values[1], event_id=values[2],
                    actor_id=values[3], archive=True)
        with self.assertRaises(ViewEventsError):
            set_event_view_archived(Cursor(), spa_id=44, workspace_id=41,
                event_id=21, actor_id=9, archive="true")

    def test_missing_or_stale_state_rejected(self):
        for archive in (True, False):
            with self.subTest(archive=archive), self.assertRaises(ViewEventsArchiveConflict):
                set_event_view_archived(Cursor(row=None), spa_id=44,
                    workspace_id=41, event_id=21, actor_id=9, archive=archive)

    def test_archive_helpers_do_not_commit(self):
        node = next(n for n in ast.parse(SERVICE).body
            if isinstance(n, ast.FunctionDef) and n.name == 'set_event_view_archived')
        body = ast.get_source_segment(SERVICE, node)
        for forbidden in ('conn.commit(', 'conn.rollback(', 'DELETE FROM',
                          'UPDATE public.event_calendar_events', 'BUSINESS_SCHEDULE'):
            self.assertNotIn(forbidden, body)

    def test_post_endpoints_present_exactly_once(self):
        self.assertEqual(APP.count('@app.route("/events/<int:event_id>/archive", methods=["POST"])'), 1)
        self.assertEqual(APP.count('@app.route("/events/<int:event_id>/restore", methods=["POST"])'), 1)

    def test_auth_workspace_subscription_guards_for_both(self):
        for name in ('peachpos_event_archive', 'peachpos_event_restore'):
            node = next(n for n in TREE.body
                if isinstance(n, ast.FunctionDef) and n.name == name)
            decorators = "\n".join(ast.get_source_segment(APP, d) or ''
                                   for d in node.decorator_list)
            self.assertIn('login_required', decorators)
            self.assertIn('spa_required', decorators)
            self.assertIn('require_subscription_feature("event_calendar")', decorators)
            self.assertIn('require_workspace_permission("can_manage_event_units")', decorators)
            self.assertIn('_ec_set_view_events_archive_state',
                          ast.get_source_segment(APP, node))

    def test_post_helper_checks_admin_csrf_and_session_scope(self):
        node = next(n for n in TREE.body
            if isinstance(n, ast.FunctionDef) and n.name == '_ec_set_view_events_archive_state')
        body = ast.get_source_segment(APP, node)
        self.assertIn('current_business_unit_membership_role_code()', body)
        self.assertIn('organization_admin', body)
        self.assertIn('_security_form_csrf_valid(', body)
        self.assertIn('_event_unit_scope()', body)
        self.assertIn('conn.commit()', body)
        self.assertIn('conn.rollback()', body)
        self.assertIn('conn.close()', body)
        self.assertNotIn('request.args.get("spa_id")', body)

    def test_read_only_view_stays_read_only(self):
        node = next(n for n in TREE.body
            if isinstance(n, ast.FunctionDef) and n.name == 'peachpos_view_events')
        body = ast.get_source_segment(APP, node)
        self.assertIn('SET TRANSACTION READ ONLY', body)
        self.assertNotIn('conn.commit()', body)
        self.assertIn('event_csrf_token=_security_form_csrf_token()', body)

    def test_jinja_valid(self):
        Environment().parse(PAGE)

    def test_only_post_forms_with_csrf(self):
        self.assertEqual(PAGE.count('method="POST"'), 2)
        self.assertEqual(PAGE.count('name="security_csrf_token"'), 2)
        self.assertIn("url_for('peachpos_event_archive'", PAGE)
        self.assertIn("url_for('peachpos_event_restore'", PAGE)

    def test_active_render_has_archive_not_restore(self):
        self.assertIn('if event.is_archived', PAGE)
        self.assertIn('>Archive</button>', PAGE)
        self.assertIn('>Restore</button>', PAGE)
        self.assertIn('ec-view-archive-form', PAGE)

    def test_confirmation_and_boundary_wording(self):
        self.assertIn('window.confirm(', PAGE)
        self.assertIn('employee assignments', PAGE)
        self.assertIn('Include on PeachWeb', PAGE)
        self.assertIn('will NOT automatically', PAGE)

    def test_no_auto_reminder_or_public_toggle(self):
        methods = ('set_event_view_archived', '_ec_set_view_events_archive_state')
        for source, name in ((SERVICE, methods[0]), (APP, methods[1])):
            node = next(n for n in ast.parse(source).body
                        if isinstance(n, ast.FunctionDef) and n.name == name)
            body = ast.get_source_segment(source, node).upper()
            for term in ('SEND_SMS', 'BUSINESS_SCHEDULE', 'INCLUDE_ON_PEACHWEB =',
                         'EVENT_CALENDAR_DAILY_SCHEDULES SET'):
                self.assertNotIn(term, body)


if __name__ == '__main__':
    unittest.main()
