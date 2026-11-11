"""EC-062-12B: isolated Flask endpoint tests without database access."""
import ast
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask, request, abort

from services.event_calendar_edit_update import (
    EventEditUpdateConflict, EventEditUpdateInvalid,
)


APP_SOURCE = Path(__file__).resolve().parents[1].joinpath("app.py").read_text()
APP_TREE = ast.parse(APP_SOURCE)
ENDPOINTS = [
    node for node in APP_TREE.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "peachpos_event_edit_save"
]


class FakeCursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, values):
        self.calls.append((sql, values))
        if "FROM public.users AS u" not in sql:
            raise AssertionError("Unexpected user identity query")

    def fetchone(self):
        return ("Jane Administrator",)


class FakeConnection:
    def __init__(self):
        self.cur = FakeCursor()
        self.closed = False

    def cursor(self):
        return self.cur

    def close(self):
        self.closed = True


class EventEditSaveEndpointTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(len(ENDPOINTS), 1)
        node = ENDPOINTS[0]
        decorators = [ast.unparse(d) for d in node.decorator_list]
        self.assertIn("login_required", decorators)
        self.assertIn("spa_required", decorators)
        self.assertIn("require_subscription_feature('event_calendar')", decorators)
        self.assertIn("require_workspace_permission('can_manage_event_units')", decorators)
        self.assertTrue(any("edit-save" in d for d in decorators))

        # Security decorators are verified above; strip for isolated direct tests.
        import copy
        compiled_node = copy.deepcopy(node)
        compiled_node.decorator_list = []
        module = ast.fix_missing_locations(ast.Module(body=[compiled_node], type_ignores=[]))
        self.flask_app = Flask(__name__)
        self.flask_app.secret_key = "offline-test-only"
        self.conn = FakeConnection()
        self.saved_args = []

        namespace = {
            "current_business_unit_membership_role_code": lambda: "organization_admin",
            "_security_form_csrf_valid": lambda x: x == "valid-csrf",
            "_event_unit_scope": lambda: (44, 41, 34),
            "get_db_connection": lambda: self.conn,
            "request": request,
            "abort": abort,
            "app": SimpleNamespace(logger=SimpleNamespace(
                error=lambda *a, **kw: None,
                exception=lambda *a, **kw: None,
            )),
        }
        exec(compile(module, "app.py", "exec"), namespace)
        self.handler = namespace[node.name]

    def invoke(self, **overrides):
        body = {
            "security_csrf_token": "valid-csrf",
            "event_payload": json.dumps({
                "event": {}, "custom_values": {}, "days": []
            }),
            "lock_token": "c12d18be-3ca0-4acd-8ba8-79ae00b71211",
            "expected_revision": "1",
        }
        body.update(overrides)
        with self.flask_app.test_request_context(
            "/events/12/edit-save", method="POST", data=body,
        ):
            response, status = self.handler(12)
            return response.get_json(), status

    def test_valid_submission_uses_server_identity_and_same_event(self):
        def fake_update(conn, payload, **kwargs):
            self.saved_args.append((conn, payload, kwargs))
            return {"event_id": 12, "revision_after": 2}
        with patch(
            "services.event_calendar_edit_update.update_event_draft",
            side_effect=fake_update,
        ):
            body, status = self.invoke()
        self.assertEqual(status, 200)
        self.assertTrue(body["saved"])
        self.assertEqual(body["event_id"], 12)
        self.assertEqual(body["event_revision"], 2)
        self.assertTrue(self.conn.closed)
        conn, payload, kwargs = self.saved_args[0]
        self.assertIs(conn, self.conn)
        self.assertEqual(kwargs["spa_id"], 44)
        self.assertEqual(kwargs["workspace_id"], 41)
        self.assertEqual(kwargs["actor_id"], 34)
        self.assertEqual(kwargs["actor_display_name"], "Jane Administrator")
        self.assertEqual(kwargs["event_id"], 12)
        self.assertEqual(kwargs["expected_revision"], 1)
        self.assertEqual(self.conn.cur.calls[0][1], (34,))

    def test_csrf_rejected_before_database_access(self):
        with self.assertRaises(Exception) as raised:
            self.invoke(security_csrf_token="wrong")
        self.assertEqual(getattr(raised.exception, "code", None), 400)
        self.assertFalse(self.conn.closed)

    def test_empty_revision_rejected_before_database(self):
        body, status = self.invoke(expected_revision="")
        self.assertEqual(status, 400)
        self.assertFalse(body["saved"])
        self.assertFalse(self.conn.closed)

    def test_invalid_json_rejected_before_database(self):
        body, status = self.invoke(event_payload="{bad-json")
        self.assertEqual(status, 400)
        self.assertFalse(body["saved"])
        self.assertFalse(self.conn.closed)

    def test_revision_conflict_returns_409(self):
        with patch(
            "services.event_calendar_edit_update.update_event_draft",
            side_effect=EventEditUpdateConflict("Session expired"),
        ):
            body, status = self.invoke()
        self.assertEqual(status, 409)
        self.assertFalse(body["saved"])
        self.assertTrue(self.conn.closed)

    def test_invalid_event_returns_422(self):
        with patch(
            "services.event_calendar_edit_update.update_event_draft",
            side_effect=EventEditUpdateInvalid("Invalid schedule"),
        ):
            body, status = self.invoke()
        self.assertEqual(status, 422)
        self.assertFalse(body["saved"])
        self.assertTrue(self.conn.closed)

    def test_create_endpoint_is_not_used(self):
        source = ast.unparse(ENDPOINTS[0])
        self.assertNotIn("save_event_draft", source)
        self.assertNotIn("submission_token", source)
        self.assertIn("update_event_draft", source)

    def test_no_client_identity_used_for_actor(self):
        with patch(
            "services.event_calendar_edit_update.update_event_draft",
            return_value={"event_id": 12, "revision_after": 2},
        ):
            _body, status = self.invoke(
                actor_id="999", spa_id="999", workspace_id="999",
                actor_display_name="Fake User",
            )
        self.assertEqual(status, 200)
        self.assertEqual(self.conn.cur.calls[0][1], (34,))


if __name__ == "__main__":
    unittest.main()
