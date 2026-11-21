"""Static security and wiring tests for introduction routes."""

import ast
import unittest
from pathlib import Path

SOURCE = Path("app.py").read_text()
TREE = ast.parse(SOURCE)


def route_function(name):
    matches = [
        node for node in TREE.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"Expected one route function: {name}"
        )
    return matches[0]


class IntroductionRouteTests(unittest.TestCase):

    def test_get_route_exists(self):
        route_function(
            "master_admin_website_intro_editor"
        )

    def test_save_route_exists(self):
        route_function(
            "master_admin_website_intro_save_draft"
        )

    def test_get_requires_login(self):
        node = route_function(
            "master_admin_website_intro_editor"
        )
        decorators = ast.unparse(node.decorator_list)
        self.assertIn("login_required", decorators)
        self.assertIn("master_admin_required", decorators)

    def test_save_requires_login(self):
        node = route_function(
            "master_admin_website_intro_save_draft"
        )
        decorators = ast.unparse(node.decorator_list)
        self.assertIn("login_required", decorators)
        self.assertIn("master_admin_required", decorators)

    def test_get_is_read_only(self):
        node = route_function(
            "master_admin_website_intro_editor"
        )
        decorators = ast.unparse(node.decorator_list)
        self.assertIn("methods=['GET']", decorators)

    def test_save_is_post_only(self):
        node = route_function(
            "master_admin_website_intro_save_draft"
        )
        decorators = ast.unparse(node.decorator_list)
        self.assertIn("methods=['POST']", decorators)

    def test_save_requires_csrf(self):
        node = route_function(
            "master_admin_website_intro_save_draft"
        )
        self.assertIn(
            "_security_form_csrf_valid",
            ast.unparse(node),
        )

    def test_save_uses_registered_section(self):
        node = route_function(
            "master_admin_website_intro_save_draft"
        )
        calls = [
            call
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "save_section_draft"
        ]

        self.assertEqual(len(calls), 1)

        values = [
            keyword.value
            for keyword in calls[0].keywords
            if keyword.arg == "section_key"
        ]

        self.assertEqual(len(values), 1)

        expected = ast.parse(
            "f'{surface}.intro'",
            mode="eval",
        ).body

        self.assertEqual(
            ast.dump(values[0]),
            ast.dump(expected),
        )

    def test_both_routes_restrict_surface(self):
        for name in (
            "master_admin_website_intro_editor",
            "master_admin_website_intro_save_draft",
        ):
            with self.subTest(name=name):
                node = route_function(name)
                code = ast.unparse(node)
                self.assertIn("'packages'", code)
                self.assertIn("'pricing'", code)
                self.assertIn("abort(404)", code)

    def test_get_uses_private_editor_template(self):
        node = route_function(
            "master_admin_website_intro_editor"
        )
        self.assertIn(
            "master_admin_website_intro.html",
            ast.unparse(node),
        )

    def test_save_does_not_publish(self):
        node = route_function(
            "master_admin_website_intro_save_draft"
        )
        self.assertNotIn(
            "publish_section",
            ast.unparse(node),
        )

    def test_revision_conflict_handled(self):
        node = route_function(
            "master_admin_website_intro_save_draft"
        )
        code = ast.unparse(node)
        self.assertIn("MarketingCMSConflict", code)
        self.assertIn(
            "expected_draft_revision_id",
            code,
        )


if __name__ == "__main__":
    unittest.main()
