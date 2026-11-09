"""Isolated handler tests for the event draft validation route.

The route function is extracted from app.py without executing
the full application or its decorators. This tests handler
behavior, not authenticated HTTP middleware integration.
"""

import ast
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask, abort, request
from werkzeug.exceptions import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.event_calendar_validation import EventValidationError
from services.event_calendar_resources import EventResourceError
from services.event_calendar_availability import EventAvailabilityError


class FakeConnection:
    def __init__(self, timezone_name):
        self.timezone_name = timezone_name
        self.statements = []
        self.rollbacks = 0
        self.closes = 0

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        self.connection.statements.append((sql, params))

    def fetchone(self):
        if self.connection.timezone_name:
            return (self.connection.timezone_name,)
        return None


class EventEndpointTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = (ROOT / "app.py").read_text()
        tree = ast.parse(source)

        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "validate_event_draft"
        ]

        if len(matches) != 1:
            raise AssertionError(
                "Expected exactly one event validation handler."
            )

        node = matches[0]

        decorators = [
            ast.get_source_segment(source, decorator)
            for decorator in node.decorator_list
        ]

        required = (
            "login_required",
            "spa_required",
            'require_subscription_feature("event_calendar")',
            'require_workspace_permission("can_manage_event_units")',
        )

        for decorator in required:
            if decorator not in decorators:
                raise AssertionError(
                    "Expected authorization decorator missing: "
                    + decorator
                )

        # Remove decorators only from this in-memory AST,
        # not from the application's actual source code.
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
        self.flask_app = Flask("event-endpoint-tests")
        self.role = "organization_admin"
        self.csrf_valid = True
        self.timezone_name = "America/Chicago"
        self.connections = []

        self.normalized = {
            "timezone_name": "America/Chicago",
            "days": [{
                "operating": True,
                "equipment_ids": [1],
                "shifts": [{"employee_id": 43}],
            }],
        }

        self.parse = self.patch_service(
            "services.event_calendar_validation.validate_event_payload",
            return_value=self.normalized,
        )

        self.coverage = self.patch_service(
            "services.event_calendar_coverage.analyze_event_coverage",
            return_value={
                "uncovered_unit_days": 0,
                "days": [],
            },
        )

        self.resources = self.patch_service(
            "services.event_calendar_resources."
            "validate_event_resource_ownership",
            return_value={"ownership_validated": True},
        )

        self.availability = self.patch_service(
            "services.event_calendar_availability."
            "validate_existing_event_availability",
            return_value={"availability_validated": True},
        )

        def get_connection():
            conn = FakeConnection(self.timezone_name)
            self.connections.append(conn)
            return conn

        namespace = {
            "__name__": "__event_endpoint_test__",
            "request": request,
            "abort": abort,
            "current_business_unit_membership_role_code":
                lambda: self.role,
            "_security_form_csrf_valid":
                lambda token: self.csrf_valid,
            "_event_unit_scope": lambda: (44, 41, 99),
            "get_db_connection": get_connection,
        }

        exec(self.handler_code, namespace)

        self.handler = namespace["validate_event_draft"]

    def patch_service(self, name, **kwargs):
        patcher = mock.patch(name, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def invoke(self, raw_payload='{}'):
        data = {
            "security_csrf_token": "test-token",
            "event_payload": raw_payload,
        }

        with self.flask_app.test_request_context(
            "/events/validate",
            method="POST",
            data=data,
        ):
            result = self.handler()

            if isinstance(result, tuple):
                response, status = result
            else:
                response, status = result, 200

            return status, response.get_json()

    def assert_connections_rolled_back(self):
        for connection in self.connections:
            self.assertEqual(connection.rollbacks, 1)
            self.assertEqual(connection.closes, 1)

            for sql, _ in connection.statements:
                command = sql.strip().upper()

                self.assertFalse(
                    command.startswith(
                        ("INSERT", "UPDATE", "DELETE", "TRUNCATE")
                    )
                )

    def test_successful_database_preflight(self):
        status, result = self.invoke()

        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertFalse(result["ready_to_save"])
        self.assertEqual(
            result["validation_level"],
            "database_preflight",
        )
        self.assertTrue(result["ownership_validated"])
        self.assertTrue(result["availability_validated"])

        self.assertEqual(len(self.connections), 2)

        for connection in self.connections:
            self.assertTrue(
                any(
                    "SET TRANSACTION READ ONLY" in sql
                    for sql, _ in connection.statements
                )
            )

        self.resources.assert_called_once()
        self.availability.assert_called_once()

        self.assertEqual(
            self.resources.call_args.args[2:],
            (44, 41),
        )
        self.assertEqual(
            self.availability.call_args.args[2],
            44,
        )

        self.assert_connections_rolled_back()

    def test_inactive_or_invalid_resource_returns_422(self):
        self.resources.side_effect = EventResourceError(
            "Selected equipment is unavailable."
        )

        status, result = self.invoke()

        self.assertEqual(status, 422)
        self.assertFalse(result["ok"])
        self.assertFalse(result["ready_to_save"])
        self.availability.assert_not_called()
        self.assert_connections_rolled_back()

    def test_existing_reservation_conflict_returns_409(self):
        self.availability.side_effect = EventAvailabilityError(
            "Equipment is already scheduled."
        )

        status, result = self.invoke()

        self.assertEqual(status, 409)
        self.assertFalse(result["ok"])
        self.assertFalse(result["ready_to_save"])
        self.assert_connections_rolled_back()

    def test_non_administrator_rejected(self):
        self.role = "employee"

        with self.assertRaises(HTTPException) as caught:
            self.invoke()

        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(self.connections, [])

    def test_invalid_csrf_rejected(self):
        self.csrf_valid = False

        with self.assertRaises(HTTPException) as caught:
            self.invoke()

        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.connections, [])

    def test_malformed_json_rejected(self):
        status, result = self.invoke("{bad-json")

        self.assertEqual(status, 400)
        self.assertFalse(result["ok"])
        self.assertFalse(result["ready_to_save"])
        self.assertEqual(self.connections, [])

    def test_invalid_event_structure_returns_422(self):
        self.parse.side_effect = EventValidationError(
            "Invalid event schedule."
        )

        status, result = self.invoke()

        self.assertEqual(status, 422)
        self.assertFalse(result["ok"])
        self.assertFalse(result["ready_to_save"])
        self.assertEqual(len(self.connections), 1)
        self.resources.assert_not_called()
        self.assert_connections_rolled_back()

    def test_missing_business_timezone_returns_422(self):
        self.timezone_name = None

        status, result = self.invoke()

        self.assertEqual(status, 422)
        self.assertFalse(result["ok"])
        self.assertFalse(result["ready_to_save"])
        self.assertEqual(len(self.connections), 1)
        self.parse.assert_not_called()
        self.assert_connections_rolled_back()


if __name__ == "__main__":
    unittest.main()
