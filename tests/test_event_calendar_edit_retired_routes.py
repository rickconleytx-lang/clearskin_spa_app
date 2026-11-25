"""EC-062-14F-2A: guard against reintroducing lease-based HTTP routes.

The former lock service and table are retired in a later independent step.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'app.py').read_text()
NODES = {n.name: n for n in ast.parse(APP).body if isinstance(n, ast.FunctionDef)}
FORM = (ROOT / 'templates/event_new.html').read_text()
CALENDAR = (ROOT / 'templates/event_calendar_month.html').read_text()


def route_values(node):
    return [child.value for d in node.decorator_list for child in ast.walk(d)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
            and child.value.startswith('/events/')]


class LegacyLeaseHTTPRetirementTests(unittest.TestCase):
    def test_no_legacy_edit_lock_endpoint(self):
        self.assertNotIn('peachpos_event_edit_lock', NODES)

    def test_no_legacy_read_endpoint(self):
        self.assertNotIn('peachpos_event_edit_data', NODES)

    def test_no_legacy_save_endpoint(self):
        self.assertNotIn('peachpos_event_edit_save', NODES)

    def test_only_lockfree_edit_data_route(self):
        node = NODES['peachpos_event_edit_draft']
        self.assertEqual(route_values(node), ['/events/<int:event_id>/edit-draft'])
        decorators = ' '.join(ast.unparse(d) for d in node.decorator_list)
        for guard in ('login_required', 'spa_required',
                      'require_subscription_feature', 'require_workspace_permission'):
            self.assertIn(guard, decorators)
        source = ast.unparse(node)
        self.assertIn('load_event_edit_payload', source)
        self.assertNotIn('lock_token', source)

    def test_only_lockfree_edit_save_route(self):
        node = NODES['peachpos_event_edit_save_unlocked']
        self.assertEqual(route_values(node), ['/events/<int:event_id>/edit-save-unlocked'])
        decorators = ' '.join(ast.unparse(d) for d in node.decorator_list)
        for guard in ('login_required', 'spa_required',
                      'require_subscription_feature', 'require_workspace_permission'):
            self.assertIn(guard, decorators)
        source = ast.unparse(node)
        for guard in ('expected_revision', 'update_event_draft', '_security_form_csrf_valid',
                      '_event_unit_scope'):
            self.assertIn(guard, source)
        self.assertNotIn('lock_token', source)

    def test_browser_uses_only_lockfree_routes(self):
        self.assertIn('"/events/" + editEventId + "/edit-draft"', FORM)
        self.assertIn('"/events/" + editEventId + "/edit-save-unlocked"', FORM)
        self.assertNotIn('data-edit-lock-url=', CALENDAR)
        self.assertNotIn('psp:peachpos:event-edit:', FORM)
        self.assertNotIn('psp:peachpos:event-edit:', CALENDAR)

    def test_authorized_server_identity_retained(self):
        save = ast.unparse(NODES['peachpos_event_edit_save_unlocked'])
        self.assertIn('actor_display_name=editor_name', save)
        self.assertIn('spa_id=spa_id', save)
        self.assertIn('workspace_id=workspace_id', save)
        self.assertIn('actor_id=actor_id', save)
        self.assertNotIn("request.form.get('actor_id')", save)


if __name__ == '__main__':
    unittest.main()
