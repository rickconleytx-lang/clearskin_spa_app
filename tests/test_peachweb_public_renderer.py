"""Test isolated public PeachWeb renderer behavior."""

import ast
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeConnection:
    def __init__(self):
        self.readonly = False
        self.cursor_closed = False
        self.rolled_back = False
        self.closed = False
        self.token = None

    def set_session(self, *, readonly):
        self.readonly = readonly

    def cursor(self):
        owner = self

        class FakeCursor:
            def close(self):
                owner.cursor_closed = True

        self.token = FakeCursor()
        return self.token

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def isolated_renderer(connection_factory):
    source = Path("app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_render_public_tenant_home"
    ]

    if len(matches) != 1:
        raise AssertionError("Public renderer not unique.")

    module = ast.Module(
        body=[matches[0]],
        type_ignores=[],
    )

    namespace = {
        "_load_public_website_content": lambda tenant: {
            "website_settings": {},
            "services": [],
            "services_two": [],
            "services_three": [],
            "additional_menu_items": [],
            "website_links": [],
        },
        "resolve_peachpos_website_defaults":
            lambda settings, style: settings,
        "_build_business_initials": lambda name: "TB",
        "render_template": lambda name, **kwargs: {
            "template": name,
            **kwargs,
        },
        "get_db_connection": connection_factory,
    }

    exec(
        compile(module, "app.py", "exec"),
        namespace,
    )

    return namespace["_render_public_tenant_home"]


class PeachWebPublicRendererTests(unittest.TestCase):
    def setUp(self):
        self.tenant = {
            "tier_code": "pos",
            "spa_id": 44,
            "business_unit_id": 41,
            "business_name": "Local Test Business",
            "public_booking_slug": "",
            "public_booking_enabled": False,
        }

    def test_peachpos_receives_public_schedule(self):
        connection = FakeConnection()
        renderer = isolated_renderer(lambda: connection)

        schedule = {
            "heading": "Where to Find Us",
            "intro": "Find us!",
            "weeks": [],
        }

        with patch(
            "services.peachweb_public_section."
            "load_public_events_section",
            return_value=schedule,
        ) as loader:
            result = renderer(self.tenant)

        loader.assert_called_once_with(
            connection.token,
            tenant=self.tenant,
        )

        self.assertIs(
            result["public_events_section"],
            schedule,
        )
        self.assertTrue(connection.readonly)
        self.assertTrue(connection.cursor_closed)
        self.assertTrue(connection.rolled_back)
        self.assertTrue(connection.closed)

    def test_solo_does_not_query_public_events(self):
        def forbidden_connection():
            raise AssertionError(
                "Solo must not open the events connection."
            )

        renderer = isolated_renderer(
            forbidden_connection
        )

        tenant = dict(
            self.tenant,
            tier_code="solo",
            public_booking_enabled=True,
        )

        result = renderer(tenant)

        self.assertIsNone(
            result["public_events_section"]
        )
        self.assertFalse(result["is_peachpos"])
        self.assertTrue(
            result["public_booking_enabled"]
        )

    def test_controller_failure_closes_connection(self):
        connection = FakeConnection()
        renderer = isolated_renderer(lambda: connection)

        with patch(
            "services.peachweb_public_section."
            "load_public_events_section",
            side_effect=RuntimeError("Test failure"),
        ):
            with self.assertRaises(RuntimeError):
                renderer(self.tenant)

        self.assertTrue(connection.cursor_closed)
        self.assertTrue(connection.rolled_back)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
