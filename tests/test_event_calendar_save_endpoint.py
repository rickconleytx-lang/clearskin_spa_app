"""Isolated tests for the PeachPOS Save Event handler.

The handler is extracted from app.py without executing its
Flask decorators. Decorator presence is checked structurally,
but full authentication middleware is NOT tested here.

All database connections and save operations are mocked.
"""

import ast
import json
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from flask import Flask, abort, request
from werkzeug.exceptions import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.event_calendar_save import (
    EventSaveConflict,
    EventSaveError,
    EventSaveInvalid,
)


class FakeConnection:
    def __init__(self):
        self.rollbacks = 0
        self.closes = 0

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


class EventSaveEndpointTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = (ROOT / "app.py").read_text()
        tree = ast.parse(source)

        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "save_peachpos_event"
        ]

        if len(matches) != 1:
            raise AssertionError(
                "Expected exactly one Save Event handler."
            )

        node = matches[0]

        decorators = [
            ast.get_source_segment(source, decorator)
            for decorator in node.decorator_list
        ]

        required = (
            'app.route("/events/save", methods=["POST"])',
            "login_required",
            "spa_required",
            'require_subscription_feature("event_calendar")',
            'require_workspace_permission("can_manage_event_units")',
        )

        for item in required:
            if item not in decorators:
                raise AssertionError(
                    "Missing Save endpoint decorator: " + item
                )

        cls.verified_decorators = True

        # Remove decorators from an in-memory copy of the AST.
        # The real app.py is never modified by these tests.
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
        self.flask_app = Flask("peachpos-save-handler-tests")
        self.flask_app.config["TESTING"] = True

        self.role = "organization_admin"
        self.csrf_valid = True
        self.conn = FakeConnection()

        self.scope = mock.Mock(
            return_value=(44, 41, 34)
        )

        self.connection_factory = mock.Mock(
            return_value=self.conn
        )

        self.csrf_check = mock.Mock(
            side_effect=lambda value: (
                self.csrf_valid and value == "valid-csrf"
            )
        )

        self.logger = mock.Mock()

        self.payload = {
            "event": {
                "name": "Save Endpoint Security Test",
            },
            "custom_values": {},
            "days": [],
        }

        self.token = str(uuid.uuid4())

        patcher = mock.patch(
            "services.event_calendar_save.save_event_draft"
        )

        self.save_service = patcher.start()
        self.addCleanup(patcher.stop)

        self.save_service.return_value = {
            "event_id": 501,
            "created": True,
            "duplicate": False,
        }

        namespace = {
            "request": request,
            "abort": abort,
            "app": SimpleNamespace(logger=self.logger),
            "current_business_unit_membership_role_code":
                lambda: self.role,
            "_security_form_csrf_valid": self.csrf_check,
            "_event_unit_scope": self.scope,
            "get_db_connection": self.connection_factory,
        }

        exec(self.handler_code, namespace)
        self.handler = namespace["save_peachpos_event"]

    def invoke(self, changes=None):
        form = {
            "security_csrf_token": "valid-csrf",
            "event_payload": json.dumps(self.payload),
            "submission_token": self.token,
        }

        if changes:
            for key, value in changes.items():
                if value is None:
                    form.pop(key, None)
                else:
                    form[key] = value

        with self.flask_app.test_request_context(
            "/events/save",
            method="POST",
            data=form,
        ):
            response, status = self.handler()
            return status, response.get_json()

    def assert_closed(self):
        self.assertEqual(self.conn.rollbacks, 1)
        self.assertEqual(self.conn.closes, 1)

    def assert_no_database_connection(self):
        self.connection_factory.assert_not_called()
        self.save_service.assert_not_called()

    def test_required_route_decorators_present(self):
        self.assertTrue(self.verified_decorators)

    def test_successful_new_event_returns_201(self):
        status, body = self.invoke()

        self.assertEqual(status, 201)
        self.assertTrue(body["ok"])
        self.assertTrue(body["saved"])
        self.assertTrue(body["created"])
        self.assertFalse(body["duplicate"])
        self.assertEqual(body["event_id"], 501)

        self.assert_closed()
        self.save_service.assert_called_once()

    def test_duplicate_retry_returns_200(self):
        self.save_service.return_value = {
            "event_id": 777,
            "created": False,
            "duplicate": True,
        }

        status, body = self.invoke()

        self.assertEqual(status, 200)
        self.assertTrue(body["saved"])
        self.assertFalse(body["created"])
        self.assertTrue(body["duplicate"])
        self.assertEqual(body["event_id"], 777)

        self.assert_closed()

    def test_scope_comes_from_server(self):
        self.payload["spa_id"] = 999
        self.payload["business_unit_id"] = 888
        self.payload["actor_id"] = 777

        status, body = self.invoke()

        self.assertEqual(status, 201)
        self.assertTrue(body["saved"])

        args = self.save_service.call_args.args

        self.assertIs(args[0], self.conn)
        self.assertEqual(args[1], self.payload)
        self.assertEqual(args[2:5], (44, 41, 34))
        self.assertEqual(args[5], self.token)

        self.scope.assert_called_once()
        self.assert_closed()

    def test_conflict_returns_409(self):
        self.save_service.side_effect = EventSaveConflict(
            "Truck is already reserved."
        )

        status, body = self.invoke()

        self.assertEqual(status, 409)
        self.assertFalse(body["saved"])
        self.assertIn("reserved", body["error"])
        self.assert_closed()

    def test_invalid_submission_returns_422(self):
        self.save_service.side_effect = EventSaveInvalid(
            "Invalid event schedule."
        )

        status, body = self.invoke()

        self.assertEqual(status, 422)
        self.assertFalse(body["saved"])
        self.assert_closed()

    def test_service_failure_returns_safe_500(self):
        self.save_service.side_effect = EventSaveError(
            "Sensitive internal diagnostic"
        )

        status, body = self.invoke()

        self.assertEqual(status, 500)
        self.assertFalse(body["saved"])
        self.assertNotIn(
            "Sensitive internal diagnostic",
            body["error"],
        )

        self.assert_closed()

    def test_unexpected_failure_does_not_leak_details(self):
        self.save_service.side_effect = RuntimeError(
            "PRIVATE_CONTACT_DATA_DO_NOT_EXPOSE"
        )

        status, body = self.invoke()

        self.assertEqual(status, 500)
        self.assertFalse(body["saved"])
        self.assertNotIn(
            "PRIVATE_CONTACT_DATA_DO_NOT_EXPOSE",
            str(body),
        )

        self.assertNotIn(
            "PRIVATE_CONTACT_DATA_DO_NOT_EXPOSE",
            str(self.logger.error.call_args),
        )

        self.assert_closed()

    def test_non_administrator_rejected(self):
        self.role = "employee"

        with self.assertRaises(HTTPException) as caught:
            self.invoke()

        self.assertEqual(caught.exception.code, 403)
        self.assert_no_database_connection()

    def test_invalid_csrf_rejected(self):
        self.csrf_valid = False

        with self.assertRaises(HTTPException) as caught:
            self.invoke()

        self.assertEqual(caught.exception.code, 400)
        self.assert_no_database_connection()

    def test_missing_csrf_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            self.invoke({
                "security_csrf_token": None,
            })

        self.assertEqual(caught.exception.code, 400)
        self.assert_no_database_connection()

    def test_missing_payload_rejected(self):
        status, body = self.invoke({
            "event_payload": None,
        })

        self.assertEqual(status, 400)
        self.assertFalse(body["saved"])
        self.assert_no_database_connection()

    def test_malformed_json_rejected(self):
        status, body = self.invoke({
            "event_payload": "{invalid-json",
        })

        self.assertEqual(status, 400)
        self.assertFalse(body["saved"])
        self.assert_no_database_connection()

    def test_non_object_json_rejected(self):
        status, body = self.invoke({
            "event_payload": json.dumps(["not", "an", "event"]),
        })

        self.assertEqual(status, 422)
        self.assertFalse(body["saved"])
        self.assert_no_database_connection()

    def test_missing_submission_token_rejected(self):
        status, body = self.invoke({
            "submission_token": None,
        })

        self.assertEqual(status, 422)
        self.assertFalse(body["saved"])
        self.assert_no_database_connection()

    def test_oversized_submission_token_rejected(self):
        status, body = self.invoke({
            "submission_token": "x" * 81,
        })

        self.assertEqual(status, 422)
        self.assertFalse(body["saved"])
        self.assert_no_database_connection()

    def test_invalid_uuid_rejected_by_save_service(self):
        self.save_service.side_effect = EventSaveInvalid(
            "Invalid submission token."
        )

        status, body = self.invoke({
            "submission_token": "not-a-uuid",
        })

        self.assertEqual(status, 422)
        self.assertFalse(body["saved"])
        self.assert_closed()

    def test_oversized_request_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            self.invoke({
                "event_payload": "x" * 600100,
            })

        self.assertEqual(caught.exception.code, 413)
        self.assert_no_database_connection()

    def test_missing_authorized_scope_rejected(self):
        self.scope.side_effect = lambda: abort(403)

        with self.assertRaises(HTTPException) as caught:
            self.invoke()

        self.assertEqual(caught.exception.code, 403)
        self.assert_no_database_connection()


if __name__ == "__main__":
    unittest.main()
