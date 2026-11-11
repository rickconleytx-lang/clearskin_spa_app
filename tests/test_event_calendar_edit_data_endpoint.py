"""Isolated Flask HTTP tests for Event Editing data retrieval.

The real application's authorization decorators are verified
structurally, then omitted in the isolated HTTP harness.

This tests the handler and request handling, not the complete
application's authentication middleware.
"""

import ast
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask, abort, request

from services.event_calendar_edit_locks import (
    EventEditLockConflict,
    EventEditLockError,
)
from services.event_calendar_edit_read import EventEditReadError


ROOT = Path(__file__).resolve().parents[1]


class EventEditDataHTTPTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = (ROOT / "app.py").read_text()
        tree = ast.parse(source)

        matches = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "peachpos_event_edit_data"
        ]

        if len(matches) != 1:
            raise AssertionError(
                "Expected exactly one edit-data handler."
            )

        node = matches[0]

        decorators = [
            ast.get_source_segment(source, item)
            for item in node.decorator_list
        ]

        required = (
            'app.route("/events/<int:event_id>/edit-data", '
            'methods=["POST"])',
            "login_required",
            "spa_required",
            'require_subscription_feature("event_calendar")',
            'require_workspace_permission("can_manage_event_units")',
        )

        for item in required:
            if item not in decorators:
                raise AssertionError(
                    "Missing edit-data decorator: " + item
                )

        cls.handler_source = ast.unparse(node)

        node.decorator_list = []

        isolated = ast.Module(
            body=[node],
            type_ignores=[],
        )

        ast.fix_missing_locations(isolated)

        cls.handler_code = compile(
            isolated,
            str(ROOT / "app.py"),
            "exec",
        )

    def setUp(self):
        self.app = Flask("peachpos-edit-data-http-test")
        self.app.config["TESTING"] = True

        self.role = "organization_admin"
        self.csrf_valid = True
        self.scope = mock.Mock(return_value=(44, 41, 34))

        self.conn = mock.MagicMock(
            name="fake-readonly-connection"
        )
        self.connection_factory = mock.Mock(
            return_value=self.conn
        )

        lock_patcher = mock.patch(
            "services.event_calendar_edit_locks."
            "require_event_edit_lock_for_read"
        )
        self.guard = lock_patcher.start()
        self.addCleanup(lock_patcher.stop)

        read_patcher = mock.patch(
            "services.event_calendar_edit_read."
            "load_event_edit_payload"
        )
        self.loader = read_patcher.start()
        self.addCleanup(read_patcher.stop)

        self.guard.return_value = 1

        self.loader.return_value = {
            "event_id": 12,
            "event_revision": 1,
            "timezone_name": "America/Chicago",
            "event": {
                "name": "Saved Test Event",
                "contact_email": "private@example.test",
            },
            "custom_values": {},
            "custom_labels": {},
            "days": [],
        }

        namespace = {
            "request": request,
            "abort": abort,
            "current_business_unit_membership_role_code":
                lambda: self.role,
            "_security_form_csrf_valid":
                lambda value: (
                    self.csrf_valid and value == "valid-csrf"
                ),
            "_event_unit_scope": self.scope,
            "get_db_connection": self.connection_factory,
        }

        exec(self.handler_code, namespace)

        handler = namespace["peachpos_event_edit_data"]

        self.app.add_url_rule(
            "/events/<int:event_id>/edit-data",
            endpoint="isolated_edit_data",
            view_func=handler,
            methods=["POST"],
        )

        self.client = self.app.test_client()

    def post(self, updates=None, event_id=12):
        data = {
            "security_csrf_token": "valid-csrf",
            "lock_token": "test-edit-session",
        }

        if updates:
            for key, value in updates.items():
                if value is None:
                    data.pop(key, None)
                else:
                    data[key] = value

        return self.client.post(
            f"/events/{event_id}/edit-data",
            data=data,
        )

    def assert_closed(self):
        self.conn.rollback.assert_called_once_with()
        self.conn.close.assert_called_once_with()

    def test_authorized_read_scoped_and_uncached(self):
        response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["ok"])
        self.assertEqual(
            response.json["event"]["event_id"], 12
        )

        self.assertEqual(
            response.headers["Cache-Control"],
            "private, no-store",
        )

        self.conn.set_session.assert_called_once_with(
            readonly=True,
            isolation_level="REPEATABLE READ",
            autocommit=False,
        )

        cursor = (
            self.conn.cursor.return_value
            .__enter__.return_value
        )

        self.guard.assert_called_once_with(
            cursor,
            spa_id=44,
            workspace_id=41,
            event_id=12,
            actor_id=34,
            lock_token="test-edit-session",
        )

        self.loader.assert_called_once_with(
            self.conn,
            event_id=12,
            spa_id=44,
            workspace_id=41,
        )

        self.assert_closed()

    def test_non_admin_rejected_before_connection(self):
        self.role = "employee"

        response = self.post()

        self.assertEqual(response.status_code, 403)
        self.connection_factory.assert_not_called()

    def test_missing_csrf_rejected(self):
        response = self.post({
            "security_csrf_token": None
        })

        self.assertEqual(response.status_code, 400)
        self.connection_factory.assert_not_called()

    def test_invalid_csrf_rejected(self):
        response = self.post({
            "security_csrf_token": "invalid"
        })

        self.assertEqual(response.status_code, 400)
        self.connection_factory.assert_not_called()

    def test_invalid_event_id_rejected(self):
        response = self.post(event_id=0)

        self.assertEqual(response.status_code, 404)
        self.connection_factory.assert_not_called()

    def test_get_method_rejected(self):
        response = self.client.get(
            "/events/12/edit-data"
        )

        self.assertEqual(response.status_code, 405)
        self.connection_factory.assert_not_called()

    def test_large_body_rejected(self):
        response = self.post({
            "padding": "x" * 9000
        })

        self.assertEqual(response.status_code, 413)
        self.connection_factory.assert_not_called()

    def test_invalid_edit_token_sanitized(self):
        self.guard.side_effect = EventEditLockError(
            "Sensitive internal information"
        )

        response = self.post()

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(
            "Sensitive internal information",
            response.get_data(as_text=True),
        )
        self.loader.assert_not_called()
        self.assert_closed()

    def test_missing_edit_token_rejected(self):
        self.guard.side_effect = EventEditLockError(
            "Invalid edit-session token."
        )

        response = self.post({
            "lock_token": None
        })

        self.assertEqual(response.status_code, 400)
        self.loader.assert_not_called()
        self.assert_closed()

    def test_expired_edit_session_rejected(self):
        self.guard.side_effect = EventEditLockConflict(
            "Editing lease expired"
        )

        response = self.post()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json["status"], "lost"
        )
        self.loader.assert_not_called()
        self.assert_closed()

    def test_revision_mismatch_rejected(self):
        self.loader.return_value["event_revision"] = 2

        response = self.post()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json["status"], "conflict"
        )
        self.assert_closed()

    def test_missing_event_rejected(self):
        self.loader.return_value = None

        response = self.post()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json["status"], "not_found"
        )
        self.assert_closed()

    def test_unloadable_event_error_sanitized(self):
        self.loader.side_effect = EventEditReadError(
            "Private stored field"
        )

        response = self.post()

        self.assertEqual(response.status_code, 409)
        self.assertNotIn(
            "Private stored field",
            response.get_data(as_text=True),
        )
        self.assert_closed()

    def test_browser_scope_values_ignored(self):
        response = self.post({
            "spa_id": "999",
            "workspace_id": "999",
            "actor_id": "999",
        })

        self.assertEqual(response.status_code, 200)

        self.loader.assert_called_once_with(
            self.conn,
            event_id=12,
            spa_id=44,
            workspace_id=41,
        )

        self.assert_closed()

    def test_no_lease_renewal_or_save_call(self):
        self.assertNotIn(
            "renew_event_edit_lock",
            self.handler_source,
        )
        self.assertNotIn(
            "require_event_edit_lock_for_save",
            self.handler_source,
        )
        self.assertNotIn(
            "conn.commit()",
            self.handler_source,
        )


if __name__ == "__main__":
    unittest.main()
