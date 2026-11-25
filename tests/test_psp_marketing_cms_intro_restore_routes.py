"""Isolated GET/POST introduction restoration route tests.

Functions are extracted without Flask decorators so the tests
exercise route logic without loading the production application.
Database and restoration services are mocked.
"""

import ast
import copy
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import (
    Flask, abort, flash, redirect, request, session,
)
from services.psp_marketing_cms_publication import (
    MarketingCMSUnpublishedRevision,
)
from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
)


GET_NAME = "master_admin_website_intro_restore_review"
POST_NAME = "master_admin_website_intro_restore_revision"


def extract_functions():
    tree = ast.parse(Path("app.py").read_text())
    found = {}

    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in (GET_NAME, POST_NAME)
        ):
            if node.name in found:
                raise AssertionError("Duplicate restoration route")
            found[node.name] = node

    if set(found) != {GET_NAME, POST_NAME}:
        raise AssertionError("Restoration routes missing")

    return found


ROUTES = extract_functions()


def compiled_routes():
    nodes = []

    for name in (GET_NAME, POST_NAME):
        node = copy.deepcopy(ROUTES[name])
        node.decorator_list = []
        nodes.append(node)

    module = ast.fix_missing_locations(
        ast.Module(body=nodes, type_ignores=[])
    )

    return compile(
        module,
        "app.py [isolated introduction restoration]",
        "exec",
    )


COMPILED = compiled_routes()


def sample_history():
    return {
        "page_key": "packages.intro",
        "draft_revision_id": 9,
        "published_revision_id": 9,
        "revisions": [
            {
                "revision_id": 9,
                "revision_number": 3,
                "is_published": True,
                "was_published": True,
                "intro": {
                    "heading": "Current",
                    "paragraph": "Current text",
                },
            },
            {
                "revision_id": 7,
                "revision_number": 2,
                "is_published": False,
                "was_published": True,
                "intro": {
                    "heading": "Earlier",
                    "paragraph": "Earlier text",
                },
            },
            {
                "revision_id": 8,
                "revision_number": 1,
                "is_published": False,
                "was_published": False,
                "intro": {
                    "heading": "TEST",
                    "paragraph": "Never published",
                },
            },
        ],
        "events": [],
    }


class IntroductionRestorationRouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "isolated-restore-test"

        self.conn = Mock()
        self.db = Mock(return_value=self.conn)
        self.render = Mock(return_value="Restoration comparison")

        loader_patch = patch(
            "services.psp_marketing_cms_intro_history."
            "load_intro_history"
        )
        self.loader = loader_patch.start()
        self.addCleanup(loader_patch.stop)
        self.loader.return_value = sample_history()

        restore_patch = patch(
            "services.psp_marketing_cms_intro_publication."
            "restore_intro_revision"
        )
        self.restore = restore_patch.start()
        self.addCleanup(restore_patch.stop)
        self.restore.return_value = {"revision_id": 7}

        namespace = {
            "abort": abort,
            "request": request,
            "session": session,
            "flash": flash,
            "redirect": redirect,
            "get_db_connection": self.db,
            "render_template": self.render,
            "url_for": lambda endpoint, **values: (
                "/test/" + endpoint + "/" + values.get("surface", "")
            ),
            "_security_form_csrf_token": lambda: "VALID-CSRF",
            "_security_form_csrf_valid": (
                lambda value: value == "VALID-CSRF"
            ),
        }

        exec(COMPILED, namespace)

        self.review_route = namespace[GET_NAME]
        self.restore_route = namespace[POST_NAME]

    def review(self, revision_id="7", surface="packages"):
        query = (
            {} if revision_id is None
            else {"revision_id": revision_id}
        )
        with self.app.test_request_context(
            "/review", query_string=query
        ):
            return self.review_route(surface)

    @staticmethod
    def valid_form():
        return {
            "security_csrf_token": "VALID-CSRF",
            "restore_confirmation": "RESTORE",
            "revision_id": "7",
            "expected_published_revision_id": "9",
        }

    def submit(self, data=None, surface="packages", actor=9):
        payload = self.valid_form() if data is None else data

        with self.app.test_request_context(
            "/restore", method="POST", data=payload
        ):
            if actor is not None:
                session["user_id"] = actor

            return self.restore_route(surface)

    def test_get_requires_login_and_master_admin(self):
        decorators = [
            ast.unparse(item)
            for item in ROUTES[GET_NAME].decorator_list
        ]
        self.assertIn("login_required", decorators)
        self.assertIn("master_admin_required", decorators)
        self.assertIn("methods=['GET']", decorators[0])

    def test_post_requires_login_and_master_admin(self):
        decorators = [
            ast.unparse(item)
            for item in ROUTES[POST_NAME].decorator_list
        ]
        self.assertIn("login_required", decorators)
        self.assertIn("master_admin_required", decorators)
        self.assertIn("methods=['POST']", decorators[0])

    def test_get_packages_review(self):
        response = self.review()

        self.assertEqual(response.status_code, 200)
        self.loader.assert_called_once_with(
            self.conn, section_key="packages.intro"
        )
        kwargs = self.render.call_args.kwargs
        self.assertEqual(kwargs["target"]["revision_id"], 7)
        self.assertEqual(kwargs["current"]["revision_id"], 9)
        self.assertEqual(kwargs["draft_revision_id"], 9)
        self.conn.close.assert_called_once()

    def test_get_pricing_isolated(self):
        response = self.review(surface="pricing")

        self.assertEqual(response.status_code, 200)
        self.loader.assert_called_once_with(
            self.conn, section_key="pricing.intro"
        )
        self.assertEqual(
            self.render.call_args.kwargs["page_label"],
            "Pricing",
        )

    def test_get_rejects_unknown_surface(self):
        with self.assertRaises(Exception) as caught:
            self.review(surface="other")
        self.assertEqual(getattr(caught.exception, "code", None), 404)
        self.db.assert_not_called()

    def test_get_requires_revision_id(self):
        with self.assertRaises(Exception) as caught:
            self.review(revision_id=None)
        self.assertEqual(getattr(caught.exception, "code", None), 404)
        self.db.assert_not_called()

    def test_get_rejects_malformed_revision_ids(self):
        for value in ("0", "-7", "abc", "7x", "9223372036854775808"):
            with self.subTest(value=value):
                with self.assertRaises(Exception) as caught:
                    self.review(revision_id=value)
                self.assertEqual(
                    getattr(caught.exception, "code", None), 404
                )
        self.db.assert_not_called()

    def test_get_rejects_never_published_revision(self):
        with self.assertRaises(Exception) as caught:
            self.review(revision_id="8")
        self.assertEqual(getattr(caught.exception, "code", None), 404)

    def test_get_rejects_current_publication(self):
        with self.assertRaises(Exception) as caught:
            self.review(revision_id="9")
        self.assertEqual(getattr(caught.exception, "code", None), 404)

    def test_get_rejects_missing_revision(self):
        with self.assertRaises(Exception) as caught:
            self.review(revision_id="99")
        self.assertEqual(getattr(caught.exception, "code", None), 404)

    def test_get_requires_current_publication(self):
        self.loader.return_value["published_revision_id"] = None

        with self.assertRaises(Exception) as caught:
            self.review()
        self.assertEqual(getattr(caught.exception, "code", None), 404)

    def test_get_requires_valid_current_revision(self):
        self.loader.return_value["revisions"][0]["is_published"] = False

        with self.assertRaises(Exception) as caught:
            self.review()
        self.assertEqual(getattr(caught.exception, "code", None), 404)

    def test_get_private_response_headers(self):
        response = self.review()

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

    def test_get_loader_failure_closes_connection(self):
        self.loader.side_effect = RuntimeError("Test failure")

        with self.assertRaises(RuntimeError):
            self.review()

        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_get_render_failure_closes_connection(self):
        self.render.side_effect = RuntimeError("Test failure")

        with self.assertRaises(RuntimeError):
            self.review()

        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_get_never_commits(self):
        self.review()

        self.conn.commit.assert_not_called()
        self.conn.rollback.assert_called_once()

    def test_post_restores_packages(self):
        response = self.submit()

        self.assertEqual(response.status_code, 302)
        self.restore.assert_called_once_with(
            self.conn,
            section_key="packages.intro",
            actor_id=9,
            revision_id=7,
            expected_published_revision_id=9,
        )
        self.assertIn(
            "master_admin_website_intro_history/packages",
            response.location,
        )
        self.conn.close.assert_called_once()

    def test_post_restores_pricing_independently(self):
        response = self.submit(surface="pricing")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.restore.call_args.kwargs["section_key"],
            "pricing.intro",
        )

    def test_post_rejects_unknown_surface(self):
        with self.assertRaises(Exception) as caught:
            self.submit(surface="other")
        self.assertEqual(getattr(caught.exception, "code", None), 404)
        self.db.assert_not_called()

    def test_post_rejects_invalid_csrf(self):
        data = self.valid_form()
        data["security_csrf_token"] = "INVALID"

        with self.assertRaises(Exception) as caught:
            self.submit(data=data)

        self.assertEqual(getattr(caught.exception, "code", None), 400)
        self.db.assert_not_called()

    def test_post_rejects_wrong_confirmation(self):
        data = self.valid_form()
        data["restore_confirmation"] = "PUBLISH"

        with self.assertRaises(Exception) as caught:
            self.submit(data=data)

        self.assertEqual(getattr(caught.exception, "code", None), 400)
        self.db.assert_not_called()

    def test_post_rejects_invalid_target(self):
        for value in ("", "0", "abc", "9223372036854775808"):
            with self.subTest(value=value):
                data = self.valid_form()
                data["revision_id"] = value

                with self.assertRaises(Exception) as caught:
                    self.submit(data=data)

                self.assertEqual(
                    getattr(caught.exception, "code", None), 400
                )
        self.db.assert_not_called()

    def test_post_rejects_invalid_expected_revision(self):
        data = self.valid_form()
        data["expected_published_revision_id"] = "-1"

        with self.assertRaises(Exception) as caught:
            self.submit(data=data)

        self.assertEqual(getattr(caught.exception, "code", None), 400)
        self.db.assert_not_called()

    def test_post_rejects_duplicate_current_revision(self):
        data = self.valid_form()
        data["revision_id"] = "9"

        with self.assertRaises(Exception) as caught:
            self.submit(data=data)

        self.assertEqual(getattr(caught.exception, "code", None), 400)
        self.db.assert_not_called()

    def test_post_rejects_invalid_actor(self):
        for actor in (None, False, 0, "not-an-id"):
            with self.subTest(actor=actor):
                with self.assertRaises(Exception) as caught:
                    self.submit(actor=actor)

                self.assertEqual(
                    getattr(caught.exception, "code", None), 403
                )
        self.db.assert_not_called()

    def test_post_unpublished_revision_redirects(self):
        self.restore.side_effect = MarketingCMSUnpublishedRevision(
            "Never published"
        )

        response = self.submit()

        self.assertEqual(response.status_code, 302)
        self.conn.close.assert_called_once()

    def test_post_conflict_redirects(self):
        self.restore.side_effect = MarketingCMSConflict(
            "Publication changed"
        )

        response = self.submit()

        self.assertEqual(response.status_code, 302)
        self.conn.close.assert_called_once()

    def test_post_unexpected_failure_closes_connection(self):
        self.restore.side_effect = RuntimeError("Simulated error")

        with self.assertRaises(RuntimeError):
            self.submit()

        self.conn.close.assert_called_once()

    def test_post_does_not_bypass_restoration_service(self):
        self.submit()

        self.restore.assert_called_once()
        self.loader.assert_not_called()
        self.conn.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
