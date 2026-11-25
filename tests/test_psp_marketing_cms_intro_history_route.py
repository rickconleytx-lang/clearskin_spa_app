"""History route and editor navigation tests.

Uses isolated Flask request contexts and mocked DB services.
Does not connect to or modify PostgreSQL.
"""

import ast
import copy
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask, abort
from jinja2 import DictLoader, Environment


ROUTE_NAME = "master_admin_website_intro_history"


def extract_route():
    tree = ast.parse(Path("app.py").read_text())

    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == ROUTE_NAME
    ]

    if len(matches) != 1:
        raise AssertionError("Expected one introduction history route")

    return matches[0]


ROUTE = extract_route()


def compile_route():
    node = copy.deepcopy(ROUTE)
    node.decorator_list = []

    module = ast.fix_missing_locations(
        ast.Module(body=[node], type_ignores=[])
    )

    return compile(
        module,
        "app.py [isolated intro history route]",
        "exec",
    )


COMPILED = compile_route()


class IntroHistoryRouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "isolated-history-test"

        context = self.app.test_request_context("/")
        context.push()
        self.addCleanup(context.pop)

        self.conn = Mock()
        self.db = Mock(return_value=self.conn)
        self.render_template = Mock(
            return_value="Private introduction history"
        )

        loader_patch = patch(
            "services.psp_marketing_cms_intro_history."
            "load_intro_history"
        )

        self.loader = loader_patch.start()
        self.addCleanup(loader_patch.stop)

        self.loader.return_value = {
            "page_key": "packages.intro",
            "draft_revision_id": 9,
            "published_revision_id": 9,
            "revisions": [],
            "events": [],
        }

        namespace = {
            "get_db_connection": self.db,
            "render_template": self.render_template,
            "abort": abort,
        }

        exec(COMPILED, namespace)
        self.history_route = namespace[ROUTE_NAME]

        editor_source = Path(
            "templates/master_admin_website_intro.html"
        ).read_text()

        self.editor_env = Environment(
            loader=DictLoader({
                "base.html":
                    "{% block content %}{% endblock %}",
                "editor.html": editor_source,
            }),
            autoescape=True,
        )

    def editor(self, surface="packages", draft_id=9):
        return self.editor_env.get_template(
            "editor.html"
        ).render(
            surface=surface,
            page_label=(
                "Subscription Packages"
                if surface == "packages"
                else "Pricing"
            ),
            content_source="saved draft",
            draft_revision_id=draft_id,
            security_csrf_token="test-token",
            intro={
                "heading": "Launch Special",
                "paragraph": "Promotional paragraph.",
            },
            url_for=lambda endpoint, **kwargs: (
                "/test/"
                + endpoint
                + "/"
                + kwargs.get("surface", "")
            ),
        )

    def test_protected_get_route(self):
        decorators = [
            ast.unparse(item)
            for item in ROUTE.decorator_list
        ]

        self.assertIn("login_required", decorators)
        self.assertIn("master_admin_required", decorators)
        self.assertIn(
            "methods=['GET']",
            decorators[0],
        )
        self.assertIn(
            "/master-admin/website/<surface>/intro/history",
            decorators[0],
        )

    def test_packages_history(self):
        response = self.history_route("packages")

        self.assertEqual(response.status_code, 200)

        self.loader.assert_called_once_with(
            self.conn,
            section_key="packages.intro",
        )

        kwargs = self.render_template.call_args.kwargs

        self.assertEqual(
            kwargs["surface"],
            "packages",
        )
        self.assertEqual(
            kwargs["page_label"],
            "Subscription Packages",
        )

        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_pricing_history(self):
        response = self.history_route("pricing")

        self.assertEqual(response.status_code, 200)

        self.loader.assert_called_once_with(
            self.conn,
            section_key="pricing.intro",
        )

        self.assertEqual(
            self.render_template.call_args.kwargs["page_label"],
            "Pricing",
        )

    def test_unknown_surface_rejected(self):
        with self.assertRaises(Exception) as error:
            self.history_route("unknown")

        self.assertEqual(
            getattr(error.exception, "code", None),
            404,
        )
        self.db.assert_not_called()

    def test_private_response_headers(self):
        response = self.history_route("packages")

        self.assertEqual(
            response.headers["Cache-Control"],
            "private, no-store, max-age=0",
        )
        self.assertEqual(
            response.headers["X-Robots-Tag"],
            "noindex, nofollow",
        )
        self.assertEqual(
            response.headers["Referrer-Policy"],
            "no-referrer",
        )

    def test_database_failure_closes_connection(self):
        self.loader.side_effect = RuntimeError(
            "Simulated database error"
        )

        with self.assertRaises(RuntimeError):
            self.history_route("packages")

        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_render_failure_still_closes_connection(self):
        self.render_template.side_effect = RuntimeError(
            "Simulated template error"
        )

        with self.assertRaises(RuntimeError):
            self.history_route("packages")

        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_history_route_does_not_commit(self):
        self.history_route("packages")

        self.conn.commit.assert_not_called()
        self.conn.rollback.assert_called_once()

    def test_packages_history_navigation(self):
        output = self.editor()

        self.assertIn(
            "/test/master_admin_website_intro_history/packages",
            output,
        )
        self.assertIn(
            "View Publication History",
            output,
        )

    def test_pricing_history_navigation(self):
        output = self.editor(
            surface="pricing",
            draft_id=None,
        )

        self.assertIn(
            "/test/master_admin_website_intro_history/pricing",
            output,
        )

    def test_history_visible_without_draft(self):
        output = self.editor(draft_id=None)

        self.assertIn(
            "View Publication History",
            output,
        )
        self.assertNotIn(
            "Review Before Publishing",
            output,
        )

    def test_existing_save_and_review_preserved(self):
        output = self.editor()

        self.assertIn("Save Draft", output)
        self.assertIn(
            "Review Before Publishing",
            output,
        )
        self.assertEqual(output.count("<form"), 1)
        self.assertEqual(output.count("</form>"), 1)

        self.assertLess(
            output.index("</form>"),
            output.index("View Publication History"),
        )


if __name__ == "__main__":
    unittest.main()
