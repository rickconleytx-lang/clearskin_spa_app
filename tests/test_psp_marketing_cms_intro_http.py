"""Real Flask routing and authorization tests for CMS intros.

Uses actual decorators and route functions from app.py.
Database connections and CSRF verification are mocked.
No production application is imported or modified.
"""

import ast
import copy
import unittest
from functools import wraps
from pathlib import Path
from unittest.mock import Mock, patch

from flask import (
    Flask, abort, flash, redirect, request,
    session, url_for, jsonify,
)

from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
)


def extract_http_code():
    tree = ast.parse(Path("app.py").read_text())

    def definitions(name):
        return [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == name
        ]

    login = definitions("login_required")
    admins = definitions("master_admin_required")

    get_routes = definitions(
        "master_admin_website_intro_editor"
    )

    save_routes = definitions(
        "master_admin_website_intro_save_draft"
    )

    if (
        len(login) != 1
        or len(admins) != 2
        or len(get_routes) != 1
        or len(save_routes) != 1
    ):
        raise AssertionError(
            "Unexpected authorization or route definitions"
        )

    active_admin = admins[-1]

    if not (
        login[0].lineno
        < active_admin.lineno
        < get_routes[0].lineno
    ):
        raise AssertionError(
            "Unexpected authorization definition order"
        )

    nodes = [
        login[0],
        active_admin,
        get_routes[0],
        save_routes[0],
    ]

    module = ast.fix_missing_locations(
        ast.Module(
            body=[copy.deepcopy(n) for n in nodes],
            type_ignores=[],
        )
    )

    return compile(
        module,
        "app.py [isolated real HTTP routes]",
        "exec",
    )


ROUTE_CODE = extract_http_code()


class IntroductionHTTPTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "isolated-http-test-only"
        self.app.config["TESTING"] = False
        self.app.logger.disabled = True

        self.conn = Mock(name="mock_connection")
        self.database = Mock(
            return_value=self.conn
        )

        self.csrf = Mock(
            side_effect=lambda value: value == "csrf-ok"
        )

        def render_intro(template, **context):
            return jsonify({
                "template": template,
                "surface": context["surface"],
                "heading": context["intro"]["heading"],
                "paragraph": context["intro"]["paragraph"],
                "source": context["content_source"],
                "revision": context["draft_revision_id"],
            })

        namespace = {
            "app": self.app,
            "wraps": wraps,
            "session": session,
            "flash": flash,
            "redirect": redirect,
            "url_for": url_for,
            "abort": abort,
            "request": request,
            "render_template": render_intro,
            "get_db_connection": self.database,
            "_security_form_csrf_token": (
                lambda: "csrf-ok"
            ),
            "_security_form_csrf_valid": self.csrf,
        }

        exec(ROUTE_CODE, namespace)

        @self.app.route("/login", endpoint="login")
        def login():
            return "Login"

        @self.app.route("/", endpoint="home")
        def home():
            return "Home"

        self.client = self.app.test_client()

        load_patch = patch(
            "services.psp_marketing_cms_service."
            "load_section_state"
        )

        save_patch = patch(
            "services.psp_marketing_cms_service."
            "save_section_draft"
        )

        self.load = load_patch.start()
        self.save = save_patch.start()

        self.addCleanup(load_patch.stop)
        self.addCleanup(save_patch.stop)

        self.load.return_value = {
            "draft_revision_id": None,
            "draft_content": None,
            "published_revision_id": None,
            "published_content": None,
        }

        self.save.return_value = {
            "revision_number": 1
        }

    def authenticate(self, role="master_admin"):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 17
            sess["role"] = role

    def get(self, surface="packages"):
        return self.client.get(
            f"/master-admin/website/{surface}/intro"
        )

    def post(self, surface="packages", **changes):
        data = {
            "security_csrf_token": "csrf-ok",
            "heading": "New heading",
            "paragraph": "First line\nSecond line",
            "expected_draft_revision_id": "",
        }
        data.update(changes)

        return self.client.post(
            f"/master-admin/website/{surface}/intro/save",
            data=data,
        )

    def test_anonymous_get_redirects_to_login(self):
        response = self.get()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.location.endswith("/login")
        )
        self.database.assert_not_called()

    def test_anonymous_post_redirects_to_login(self):
        response = self.post()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.location.endswith("/login")
        )
        self.database.assert_not_called()

    def test_business_user_get_denied(self):
        self.authenticate("owner")

        response = self.get()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.location.endswith("/")
        )
        self.database.assert_not_called()

    def test_business_user_post_denied(self):
        self.authenticate("owner")

        response = self.post()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.location.endswith("/")
        )
        self.database.assert_not_called()

    def test_user_role_fallback_does_not_grant_access(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 17
            sess["user_role"] = "master_admin"

        response = self.get()

        self.assertEqual(response.status_code, 302)
        self.database.assert_not_called()

    def test_master_admin_get_packages(self):
        self.authenticate()

        response = self.get()

        self.assertEqual(response.status_code, 200)

        data = response.get_json()

        self.assertEqual(
            data["surface"], "packages"
        )
        self.assertIn(
            "LAUNCH10", data["paragraph"]
        )

        self.load.assert_called_once_with(
            self.conn,
            section_key="packages.intro",
        )

        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_master_admin_get_pricing_draft(self):
        self.authenticate()

        self.load.return_value = {
            "draft_revision_id": 8,
            "draft_content": {
                "intro": {
                    "heading": "Pricing draft",
                    "paragraph": "Pricing text",
                }
            },
            "published_revision_id": None,
            "published_content": None,
        }

        response = self.get("pricing")

        self.assertEqual(response.status_code, 200)

        data = response.get_json()

        self.assertEqual(
            data["heading"], "Pricing draft"
        )
        self.assertEqual(
            data["source"], "saved draft"
        )
        self.assertEqual(data["revision"], 8)

    def test_independent_sections_over_http(self):
        self.authenticate()

        def load_state(conn, *, section_key):
            name = (
                "Packages"
                if section_key == "packages.intro"
                else "Pricing"
            )
            return {
                "draft_revision_id": 3,
                "draft_content": {
                    "intro": {
                        "heading": name + " heading",
                        "paragraph": name + " paragraph",
                    }
                },
                "published_revision_id": None,
                "published_content": None,
            }

        self.load.side_effect = load_state

        packages = self.get("packages")
        pricing = self.get("pricing")

        self.assertEqual(
            packages.get_json()["heading"],
            "Packages heading",
        )
        self.assertEqual(
            pricing.get_json()["heading"],
            "Pricing heading",
        )

    def test_missing_csrf_returns_400(self):
        self.authenticate()

        response = self.post(
            security_csrf_token=""
        )

        self.assertEqual(response.status_code, 400)
        self.database.assert_not_called()

    def test_invalid_csrf_returns_400(self):
        self.authenticate()

        response = self.post(
            security_csrf_token="incorrect"
        )

        self.assertEqual(response.status_code, 400)
        self.database.assert_not_called()

    def test_master_admin_valid_save(self):
        self.authenticate()

        response = self.post(
            "pricing",
            expected_draft_revision_id="12",
        )

        self.assertEqual(response.status_code, 302)

        self.save.assert_called_once_with(
            self.conn,
            section_key="pricing.intro",
            content={
                "intro": {
                    "heading": "New heading",
                    "paragraph": "First line\nSecond line",
                }
            },
            actor_id=17,
            expected_draft_revision_id=12,
        )

        self.conn.close.assert_called_once()

    def test_stale_revision_conflict(self):
        self.authenticate()

        self.save.side_effect = MarketingCMSConflict(
            "Stale draft"
        )

        response = self.post()

        self.assertEqual(response.status_code, 302)
        self.save.assert_called_once()
        self.conn.close.assert_called_once()

    def test_invalid_revision_returns_400(self):
        self.authenticate()

        response = self.post(
            expected_draft_revision_id="not-a-number"
        )

        self.assertEqual(response.status_code, 400)
        self.database.assert_not_called()

    def test_unknown_surface_rejected(self):
        self.authenticate()

        self.assertEqual(
            self.get("unknown").status_code, 404
        )
        self.assertEqual(
            self.post("unknown").status_code, 404
        )

        self.database.assert_not_called()

    def test_http_methods_restricted(self):
        self.authenticate()

        get_only = self.client.post(
            "/master-admin/website/packages/intro"
        )

        post_only = self.client.get(
            "/master-admin/website/packages/intro/save"
        )

        self.assertEqual(get_only.status_code, 405)
        self.assertEqual(post_only.status_code, 405)
        self.database.assert_not_called()

    def test_database_error_closes_connection(self):
        self.authenticate()

        self.load.side_effect = RuntimeError(
            "Simulated database error"
        )

        response = self.get()

        self.assertEqual(response.status_code, 500)

        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
