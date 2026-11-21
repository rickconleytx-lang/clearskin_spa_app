"""Isolated behavioral tests for introduction review/publish.

Uses actual route bodies, mocked database/service dependencies,
and a private Flask request context. No database writes.
"""

import ast
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask, abort
from werkzeug.exceptions import HTTPException

from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
)


NAMES = (
    "master_admin_website_intro_publish_review",
    "master_admin_website_intro_publish_draft",
)


def extract_routes():
    tree = ast.parse(Path("app.py").read_text())
    functions = []

    for name in NAMES:
        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == name
        ]

        if len(matches) != 1:
            raise AssertionError("Missing route: " + name)

        node = copy.deepcopy(matches[0])
        functions.append(node)

    return functions


ROUTES = extract_routes()


def compiled_routes():
    nodes = copy.deepcopy(ROUTES)

    for node in nodes:
        node.decorator_list = []

    module = ast.fix_missing_locations(
        ast.Module(body=nodes, type_ignores=[])
    )

    return compile(
        module,
        "app.py [isolated intro publication routes]",
        "exec",
    )


COMPILED = compiled_routes()


def content(heading="Launch Special"):
    return {
        "intro": {
            "heading": heading,
            "paragraph": "Promotional paragraph.",
        }
    }


def state(
    draft_id=9,
    draft_content=None,
    published_id=None,
    published_content=None,
):
    return {
        "draft_revision_id": draft_id,
        "draft_content": (
            content()
            if draft_content is None and draft_id is not None
            else draft_content
        ),
        "published_revision_id": published_id,
        "published_content": published_content,
    }


class IntroductionPublishRouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "isolated-intro-review-test"
        self.request_context = self.app.test_request_context("/")
        self.request_context.push()
        self.addCleanup(self.request_context.pop)

        self.conn = Mock()
        self.database = Mock(return_value=self.conn)
        self.render = Mock(return_value="Private review")
        self.flash = Mock()

        self.form = {}

        self.namespace = {
            "get_db_connection": self.database,
            "render_template": self.render,
            "flash": self.flash,
            "abort": abort,
            "request": SimpleNamespace(form=self.form),
            "session": {"user_id": 17},
            "redirect": lambda location: "redirect:" + location,
            "url_for": lambda endpoint, surface: (
                "/" + surface + "/" + endpoint
            ),
            "_security_form_csrf_token": (
                lambda: "csrf-test"
            ),
            "_security_form_csrf_valid": (
                lambda value: value == "csrf-test"
            ),
        }

        exec(COMPILED, self.namespace)

        self.review = self.namespace[NAMES[0]]
        self.publish = self.namespace[NAMES[1]]

        load_patch = patch(
            "services.psp_marketing_cms_service."
            "load_section_state"
        )
        publish_patch = patch(
            "services.psp_marketing_cms_intro_publication."
            "publish_intro_draft"
        )

        self.load = load_patch.start()
        self.publish_service = publish_patch.start()

        self.addCleanup(load_patch.stop)
        self.addCleanup(publish_patch.stop)

        self.load.return_value = state()
        self.publish_service.return_value = {
            "revision_id": 9
        }

    def confirm(self, **changes):
        self.form.update({
            "security_csrf_token": "csrf-test",
            "publish_confirmation": "PUBLISH",
            "expected_draft_revision_id": "9",
            "expected_published_revision_id": "",
        })
        self.form.update(changes)

    def test_actual_route_decorators_and_methods(self):
        decorators = [
            [ast.unparse(item) for item in node.decorator_list]
            for node in ROUTES
        ]

        for values in decorators:
            self.assertIn("login_required", values)
            self.assertIn("master_admin_required", values)

        self.assertIn("methods=['GET']", decorators[0][0])
        self.assertIn("methods=['POST']", decorators[1][0])

    def test_review_loads_packages_draft(self):
        response = self.review("packages")

        self.assertEqual(response.status_code, 200)

        self.load.assert_called_once_with(
            self.conn,
            section_key="packages.intro",
        )

        kwargs = self.render.call_args.kwargs

        self.assertEqual(
            kwargs["draft_revision_id"], 9
        )
        self.assertEqual(
            kwargs["draft_intro"]["heading"],
            "Launch Special",
        )
        self.assertEqual(
            kwargs["surface"], "packages"
        )
        self.conn.close.assert_called_once()

    def test_review_loads_existing_publication(self):
        self.load.return_value = state(
            published_id=7,
            published_content=content("Earlier edition"),
        )

        self.review("pricing")

        kwargs = self.render.call_args.kwargs

        self.assertEqual(kwargs["published_revision_id"], 7)
        self.assertEqual(
            kwargs["published_intro"]["heading"],
            "Earlier edition",
        )

    def test_review_has_private_headers(self):
        response = self.review("packages")

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

    def test_review_without_draft_redirects(self):
        self.load.return_value = state(draft_id=None)

        response = self.review("packages")

        self.assertIn("redirect:", response)
        self.render.assert_not_called()
        self.conn.close.assert_called_once()

    def test_review_rejects_inconsistent_publication(self):
        self.load.return_value = state(
            published_id=7,
            published_content=None,
        )

        with self.assertRaises(HTTPException) as error:
            self.review("packages")

        self.assertEqual(error.exception.code, 500)

    def test_review_rejects_unknown_surface(self):
        with self.assertRaises(HTTPException) as error:
            self.review("unknown")

        self.assertEqual(error.exception.code, 404)
        self.database.assert_not_called()

    def test_review_database_failure_closes(self):
        self.load.side_effect = RuntimeError("DB read failure")

        with self.assertRaises(RuntimeError):
            self.review("packages")

        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_publish_requires_valid_csrf(self):
        self.confirm(security_csrf_token="bad")

        with self.assertRaises(HTTPException) as error:
            self.publish("packages")

        self.assertEqual(error.exception.code, 400)
        self.database.assert_not_called()

    def test_publish_requires_confirmation(self):
        self.confirm(publish_confirmation="YES")

        with self.assertRaises(HTTPException) as error:
            self.publish("pricing")

        self.assertEqual(error.exception.code, 400)
        self.database.assert_not_called()

    def test_publish_rejects_invalid_actor(self):
        self.confirm()
        self.namespace["session"]["user_id"] = None

        with self.assertRaises(HTTPException) as error:
            self.publish("packages")

        self.assertEqual(error.exception.code, 403)
        self.database.assert_not_called()

    def test_publish_requires_both_revision_fields(self):
        self.confirm()
        del self.form["expected_published_revision_id"]

        with self.assertRaises(HTTPException) as error:
            self.publish("packages")

        self.assertEqual(error.exception.code, 400)
        self.database.assert_not_called()

    def test_publish_rejects_invalid_revision(self):
        self.confirm(expected_draft_revision_id="-1")

        with self.assertRaises(HTTPException) as error:
            self.publish("packages")

        self.assertEqual(error.exception.code, 400)
        self.database.assert_not_called()

    def test_publish_calls_protected_service(self):
        self.confirm(expected_published_revision_id="7")

        response = self.publish("pricing")

        self.assertIn("redirect:", response)

        self.publish_service.assert_called_once_with(
            self.conn,
            section_key="pricing.intro",
            actor_id=17,
            expected_draft_revision_id=9,
            expected_published_revision_id=7,
        )

        self.conn.close.assert_called_once()

    def test_publish_handles_stale_revision(self):
        self.confirm()

        self.publish_service.side_effect = MarketingCMSConflict(
            "Stale publication"
        )

        result = self.publish("packages")

        self.assertIn("redirect:", result)
        self.assertIn(
            "review",
            result,
        )
        self.conn.close.assert_called_once()

    def test_publish_database_failure_closes(self):
        self.confirm()

        self.publish_service.side_effect = RuntimeError(
            "Simulated database failure"
        )

        with self.assertRaises(RuntimeError):
            self.publish("packages")

        self.conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
