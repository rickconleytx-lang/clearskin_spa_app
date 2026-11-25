"""Website Settings CSRF regression contracts."""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]


class WebsiteSettingsCSRFTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app_source = (ROOT / "app.py").read_text(
            encoding="utf-8"
        )
        cls.template_source = (
            ROOT / "templates/public_website_settings.html"
        ).read_text(encoding="utf-8")

        tree = ast.parse(cls.app_source)
        routes = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "public_website_settings"
        ]
        assert len(routes) == 1
        cls.route = routes[0]
        cls.route_source = ast.get_source_segment(
            cls.app_source, cls.route
        )

    def test_normal_form_contains_csrf_token(self):
        start = self.template_source.index(
            '<form method="POST">'
        )
        end = self.template_source.index(
            "</form>", start
        )
        form = self.template_source[start:end]

        self.assertIn(
            'name="security_csrf_token"', form
        )
        self.assertIn(
            'value="{{ g.peachweb_settings_csrf_token }}"',
            form,
        )

    def test_csrf_guard_precedes_database_connection(self):
        source = self.route_source

        self.assertIn(
            'request.form.get("security_csrf_token")',
            source,
        )
        self.assertIn(
            '_security_form_csrf_valid(', source
        )

        self.assertLess(
            source.index("_security_form_csrf_valid("),
            source.index("get_db_connection()"),
        )

        guards = [
            node for node in self.route.body
            if isinstance(node, ast.If)
            and "_security_form_csrf_valid" in ast.unparse(
                node.test
            )
        ]

        self.assertEqual(len(guards), 1)
        self.assertEqual(
            ast.unparse(guards[0].body[0]),
            "abort(403)",
        )

    def test_guard_rejects_missing_and_invalid_tokens(self):
        guards = [
            node for node in self.route.body
            if isinstance(node, ast.If)
            and "_security_form_csrf_valid" in ast.unparse(
                node.test
            )
        ]
        self.assertEqual(len(guards), 1)

        condition = compile(
            ast.Expression(guards[0].test),
            "<website-settings-csrf-guard>",
            "eval",
        )

        for method, token, should_reject in (
            ("POST", None, True),
            ("POST", "wrong-token", True),
            ("POST", "valid-token", False),
            ("GET", None, False),
        ):
            request = SimpleNamespace(
                method=method,
                form=(
                    {}
                    if token is None
                    else {"security_csrf_token": token}
                ),
            )
            globals_for_test = {
                "request": request,
                "_security_form_csrf_valid": (
                    lambda value: value == "valid-token"
                ),
            }
            with self.subTest(method=method, token=token):
                self.assertEqual(
                    eval(condition, globals_for_test),
                    should_reject,
                )

    def test_token_available_before_all_render_paths(self):
        source = self.route_source
        self.assertIn(
            "g.peachweb_settings_csrf_token = "
            "_security_form_csrf_token()",
            source,
        )

        render_calls = [
            node for node in ast.walk(self.route)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "render_template"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "public_website_settings.html"
        ]

        self.assertGreaterEqual(len(render_calls), 1)

        token_assignments = [
            node for node in ast.walk(self.route)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute)
                and target.attr == "peachweb_settings_csrf_token"
                for target in node.targets
            )
        ]

        self.assertEqual(len(token_assignments), 1)
        self.assertTrue(all(
            token_assignments[0].lineno < call.lineno
            for call in render_calls
        ))

    def test_token_value_is_html_escaped(self):
        start = self.template_source.index(
            '<form method="POST">'
        )
        end = self.template_source.index(
            '<section class="website-settings-section">',
            start,
        )
        snippet = self.template_source[start:end]

        env = Environment(
            autoescape=True,
            undefined=StrictUndefined,
        )
        result = env.from_string(snippet).render(
            g=SimpleNamespace(
                peachweb_settings_csrf_token=(
                    '"><script>alert(1)</script>'
                )
            )
        )

        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)

    def test_onboarding_form_remains_separate(self):
        self.assertIn(
            "'complete_public_website_settings_onboarding'",
            self.template_source,
        )


if __name__ == "__main__":
    unittest.main()
