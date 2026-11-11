"""Structural route tests for PeachPOS editing-lock API."""

import ast
import unittest
from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "app.py"


class EventEditLockEndpointTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text())

        matches = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "peachpos_event_edit_lock"
        ]

        if len(matches) != 1:
            raise AssertionError(
                "Exactly one Event Edit lock endpoint required."
            )

        cls.route = matches[0]
        cls.source = ast.unparse(cls.route)

    def test_post_only_route(self):
        decorators = [
            ast.unparse(item)
            for item in self.route.decorator_list
        ]

        self.assertTrue(
            any(
                "/events/<int:event_id>/edit-lock" in value
                and "POST" in value
                for value in decorators
            )
        )

    def test_authentication_decorators(self):
        decorators = [
            ast.unparse(item)
            for item in self.route.decorator_list
        ]

        self.assertIn("login_required", decorators)
        self.assertIn("spa_required", decorators)

    def test_subscription_and_workspace_permission(self):
        decorators = " ".join(
            ast.unparse(item)
            for item in self.route.decorator_list
        )

        self.assertIn("event_calendar", decorators)
        self.assertIn("can_manage_event_units", decorators)

    def test_business_administrator_required(self):
        self.assertIn("organization_admin", self.source)
        self.assertIn("abort(403)", self.source)

    def test_csrf_required(self):
        self.assertIn(
            "_security_form_csrf_valid",
            self.source,
        )
        self.assertIn(
            "security_csrf_token",
            self.source,
        )

    def test_workspace_scope_from_server(self):
        self.assertIn(
            "_event_unit_scope()",
            self.source,
        )
        self.assertIn(
            "'actor_id': actor_id",
            self.source,
        )

    def test_all_three_operations(self):
        self.assertIn(
            "acquire_event_edit_lock",
            self.source,
        )
        self.assertIn(
            "renew_event_edit_lock",
            self.source,
        )
        self.assertIn(
            "release_event_edit_lock",
            self.source,
        )

    def test_busy_response_and_no_cache(self):
        self.assertIn(
            "return respond(result, 409)",
            self.source,
        )
        self.assertIn(
            "Cache-Control",
            self.source,
        )
        self.assertIn(
            "no-store",
            self.source,
        )

    def test_connection_always_closed(self):
        self.assertIn("finally:", self.source)
        self.assertIn("conn.close()", self.source)

    def test_payload_size_limited(self):
        self.assertIn(
            "request.content_length > 8192",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
