"""HTTP handler tests for PeachPOS editing-lock operations.

The handler is extracted from app.py without executing its real
authentication decorators or importing the full application.

Flask's test client exercises real HTTP request parsing, methods,
status codes and JSON handling. Database services are mocked.

These tests DO NOT prove production login, subscription, or
workspace middleware enforcement. Those require separate tests
against the assembled application.
"""

import ast
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask, abort, request

from services.event_calendar_edit_locks import EventEditLockError


ROOT = Path(__file__).resolve().parents[1]


class EventEditLockHTTPTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = (ROOT / "app.py").read_text()
        tree = ast.parse(source)

        matches = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "peachpos_event_edit_lock"
        ]

        if len(matches) != 1:
            raise AssertionError(
                "Exactly one editing-lock handler required."
            )

        node = matches[0]

        decorators = [
            ast.get_source_segment(source, item)
            for item in node.decorator_list
        ]

        required = (
            'app.route("/events/<int:event_id>/edit-lock", '
            'methods=["POST"])',
            "login_required",
            "spa_required",
            'require_subscription_feature("event_calendar")',
            'require_workspace_permission("can_manage_event_units")',
        )

        for decorator in required:
            if decorator not in decorators:
                raise AssertionError(
                    "Missing required decorator: " + decorator
                )

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
        self.app = Flask("peachpos-edit-lock-http-tests")
        self.app.config["TESTING"] = True

        self.role = "organization_admin"
        self.csrf_valid = True

        self.scope = mock.Mock(
            return_value=(44, 41, 34)
        )

        self.conn = mock.Mock(name="fake-db-connection")

        self.connection_factory = mock.Mock(
            return_value=self.conn
        )

        patch_targets = {
            "acquire": (
                "services.event_calendar_edit_locks."
                "acquire_event_edit_lock"
            ),
            "renew": (
                "services.event_calendar_edit_locks."
                "renew_event_edit_lock"
            ),
            "release": (
                "services.event_calendar_edit_locks."
                "release_event_edit_lock"
            ),
        }

        self.services = {}

        for key, name in patch_targets.items():
            patcher = mock.patch(name)
            self.services[key] = patcher.start()
            self.addCleanup(patcher.stop)

        self.services["acquire"].return_value = {
            "status": "acquired",
            "lock_token": "test-session-token",
            "event_revision": 1,
            "expires_at": "2026-11-11T01:00:00+00:00",
        }

        self.services["renew"].return_value = {
            "status": "renewed",
            "event_revision": 1,
            "expires_at": "2026-11-11T01:05:00+00:00",
        }

        self.services["release"].return_value = {
            "released": True,
        }

        namespace = {
            "request": request,
            "abort": abort,
            "current_business_unit_membership_role_code":
                lambda: self.role,
            "_security_form_csrf_valid":
                lambda token: (
                    self.csrf_valid and token == "valid-csrf"
                ),
            "_event_unit_scope": self.scope,
            "get_db_connection": self.connection_factory,
        }

        exec(self.handler_code, namespace)

        self.handler = namespace["peachpos_event_edit_lock"]

        self.app.add_url_rule(
            "/events/<int:event_id>/edit-lock",
            endpoint="isolated_edit_lock",
            view_func=self.handler,
            methods=["POST"],
        )

        self.client = self.app.test_client()

    def post(self, action="acquire", event_id=12,
             updates=None):
        data = {
            "security_csrf_token": "valid-csrf",
            "action": action,
            "lock_token": "test-session-token",
        }

        if updates:
            for key, value in updates.items():
                if value is None:
                    data.pop(key, None)
                else:
                    data[key] = value

        return self.client.post(
            f"/events/{event_id}/edit-lock",
            data=data,
        )

    def assert_no_connection(self):
        self.connection_factory.assert_not_called()

    def assert_closed(self):
        self.conn.close.assert_called_once_with()

    def test_acquire_returns_session_and_revision(self):
        response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json["status"], "acquired"
        )
        self.assertEqual(
            response.json["event_revision"], 1
        )
        self.assertIn("lock_token", response.json)
        self.assertEqual(
            response.headers.get("Cache-Control"),
            "no-store",
        )

        self.services["acquire"].assert_called_once_with(
            self.conn,
            spa_id=44,
            workspace_id=41,
            event_id=12,
            actor_id=34,
        )

        self.assert_closed()

    def test_busy_event_returns_conflict(self):
        self.services["acquire"].return_value = {
            "status": "busy",
            "editor_display_name": "Jane Administrator",
            "expires_at": "2026-11-11T01:00:00+00:00",
        }

        response = self.post()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["status"], "busy")
        self.assertEqual(
            response.json["editor_display_name"],
            "Jane Administrator",
        )
        self.assertNotIn("lock_token", response.json)
        self.assertNotIn("email", response.json)
        self.assert_closed()

    def test_missing_event_returns_404(self):
        self.services["acquire"].return_value = {
            "status": "not_found"
        }

        response = self.post()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json["status"], "not_found"
        )
        self.assert_closed()

    def test_renew_success(self):
        response = self.post("renew")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "renewed")

        self.services["renew"].assert_called_once_with(
            self.conn,
            spa_id=44,
            workspace_id=41,
            event_id=12,
            actor_id=34,
            lock_token="test-session-token",
        )

        self.assert_closed()

    def test_renew_lost_returns_409(self):
        self.services["renew"].return_value = {
            "status": "lost"
        }

        response = self.post("renew")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["status"], "lost")
        self.assert_closed()

    def test_release_success(self):
        response = self.post("release")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["released"])

        self.services["release"].assert_called_once_with(
            self.conn,
            spa_id=44,
            workspace_id=41,
            event_id=12,
            actor_id=34,
            lock_token="test-session-token",
        )

        self.assert_closed()

    def test_release_wrong_session_returns_409(self):
        self.services["release"].return_value = {
            "released": False
        }

        response = self.post("release")

        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json["released"])
        self.assert_closed()

    def test_non_administrator_rejected(self):
        self.role = "employee"

        response = self.post()

        self.assertEqual(response.status_code, 403)
        self.assert_no_connection()
        self.scope.assert_not_called()

    def test_missing_csrf_rejected(self):
        response = self.post(
            updates={"security_csrf_token": None}
        )

        self.assertEqual(response.status_code, 400)
        self.assert_no_connection()
        self.scope.assert_not_called()

    def test_invalid_csrf_rejected(self):
        response = self.post(
            updates={"security_csrf_token": "incorrect"}
        )

        self.assertEqual(response.status_code, 400)
        self.assert_no_connection()

    def test_unknown_action_rejected(self):
        response = self.post("delete_everything")

        self.assertEqual(response.status_code, 400)
        self.assert_no_connection()

    def test_invalid_event_id_rejected(self):
        response = self.post(event_id=0)

        self.assertEqual(response.status_code, 404)
        self.assert_no_connection()

    def test_oversized_body_rejected(self):
        response = self.post(
            updates={"padding": "x" * 9000}
        )

        self.assertEqual(response.status_code, 413)
        self.assert_no_connection()

    def test_edit_session_error_is_sanitized(self):
        self.services["renew"].side_effect = (
            EventEditLockError("Internal session details")
        )

        response = self.post("renew")

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(
            "Internal session details",
            response.get_data(as_text=True),
        )
        self.assert_closed()

    def test_browser_supplied_scope_is_ignored(self):
        response = self.post(
            updates={
                "spa_id": "999",
                "workspace_id": "999",
                "actor_id": "999",
            }
        )

        self.assertEqual(response.status_code, 200)

        self.services["acquire"].assert_called_once_with(
            self.conn,
            spa_id=44,
            workspace_id=41,
            event_id=12,
            actor_id=34,
        )

        self.assert_closed()

    def test_get_method_not_allowed(self):
        response = self.client.get(
            "/events/12/edit-lock"
        )

        self.assertEqual(response.status_code, 405)
        self.assert_no_connection()


if __name__ == "__main__":
    unittest.main()
