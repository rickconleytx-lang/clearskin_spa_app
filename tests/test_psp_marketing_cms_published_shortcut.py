import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jinja2 import Environment
from werkzeug.exceptions import (
    InternalServerError,
    abort,
)

from services.psp_marketing_cms_content import (
    MarketingContentError,
)


def hero(text):
    return {
        "primary_button_text": text,
        "secondary_button_text": "View Pricing",
        "pricing_sentence": (
            "Solo is $49/month or $490/year "
            "after the 10-day free trial."
        ),
    }


def sample_state():
    return {
        "draft_revision_id": 2,
        "draft_content": {
            "hero": hero("UNPUBLISHED DRAFT WORDING"),
        },
        "published_revision_id": 1,
        "published_content": {
            "hero": hero("Start Your free trial today"),
        },
    }


class FakeResponse:
    def __init__(self, body):
        self.body = body
        self.headers = {}


class MarketingCMSPublishedShortcutTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(
            Path("app.py").read_text(encoding="utf-8")
        )

        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == (
                "master_admin_website_home_published"
            )
        ]

        assert len(matches) == 1

        route = matches[0]

        cls.decorators = [
            ast.unparse(item)
            for item in route.decorator_list
        ]

        route.decorator_list = []

        cls.code = compile(
            ast.fix_missing_locations(
                ast.Module(
                    body=[route],
                    type_ignores=[],
                )
            ),
            "app.py",
            "exec",
        )

        cls.editor = Path(
            "templates/master_admin_website_management.html"
        ).read_text(encoding="utf-8")

    def invoke(
        self,
        host="127.0.0.1:5055",
        state=None,
        service_error=None,
    ):
        conn = MagicMock()
        factory = MagicMock(return_value=conn)
        csrf = MagicMock(return_value="contact-token")

        namespace = {
            "request": SimpleNamespace(host=host),
            "get_db_connection": factory,
            "_public_security_csrf_token": csrf,
            "render_template": (
                lambda name, **kwargs: (name, kwargs)
            ),
            "redirect": (
                lambda destination, code=302: (
                    "redirect", destination, code
                )
            ),
            "abort": abort,
        }

        exec(self.code, namespace)

        with patch(
            "services.psp_marketing_cms_service."
            "load_home_state",
            return_value=(
                sample_state()
                if state is None
                else state
            ),
            side_effect=service_error,
        ) as loader, patch(
            "flask.make_response",
            side_effect=lambda body: FakeResponse(body),
        ):
            try:
                response = namespace[
                    "master_admin_website_home_published"
                ]()
                failure = None
            except Exception as exc:
                response = None
                failure = exc

        return (
            response,
            failure,
            conn,
            factory,
            loader,
            csrf,
        )

    def test_route_is_protected_and_get_only(self):
        self.assertIn(
            "login_required", self.decorators
        )
        self.assertIn(
            "master_admin_required", self.decorators
        )
        self.assertTrue(any(
            "/master-admin/website/home/published" in item
            and "GET" in item
            for item in self.decorators
        ))

    def test_local_uses_published_revision_only(self):
        response, error, conn, _, loader, csrf = (
            self.invoke()
        )

        self.assertIsNone(error)
        self.assertEqual(
            response.body[0],
            "public_site/psp_home.html",
        )

        context = response.body[1]

        self.assertEqual(
            context["cms_home_hero"][
                "primary_button_text"
            ],
            "Start Your free trial today",
        )

        self.assertNotIn(
            "UNPUBLISHED DRAFT WORDING",
            str(context),
        )

        self.assertNotIn("cms_preview", context)
        self.assertEqual(
            context["contact_csrf_token"],
            "contact-token",
        )

        loader.assert_called_once_with(conn)
        csrf.assert_called_once_with("public_contact")
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

    def test_localhost_with_port_is_supported(self):
        response, error, _, factory, _, _ = (
            self.invoke(host="localhost:5055")
        )

        self.assertIsNone(error)
        self.assertIsInstance(
            response, FakeResponse
        )
        factory.assert_called_once()

    def test_ipv6_loopback_is_supported(self):
        response, error, _, factory, _, _ = (
            self.invoke(host="[::1]:5055")
        )

        self.assertIsNone(error)
        self.assertIsInstance(
            response, FakeResponse
        )
        factory.assert_called_once()

    def test_production_redirects_to_real_site(self):
        response, error, _, factory, loader, csrf = (
            self.invoke(host="app.peachsuitepro.com")
        )

        self.assertIsNone(error)
        self.assertEqual(
            response,
            (
                "redirect",
                "https://peachsuitepro.com/",
                302,
            ),
        )

        factory.assert_not_called()
        loader.assert_not_called()
        csrf.assert_not_called()

    def test_other_external_hosts_do_not_view_local(self):
        for host in (
            "peachsuitepro.com",
            "www.peachsuitepro.com",
            "example.com",
        ):
            with self.subTest(host=host):
                response, error, _, factory, _, _ = (
                    self.invoke(host=host)
                )

                self.assertIsNone(error)
                self.assertEqual(
                    response[0], "redirect"
                )
                factory.assert_not_called()

    def test_no_published_revision_uses_fallback(self):
        state = sample_state()
        state["published_revision_id"] = None
        state["published_content"] = None

        response, error, conn, _, _, _ = (
            self.invoke(state=state)
        )

        self.assertIsNone(error)
        self.assertNotIn(
            "cms_home_hero",
            response.body[1],
        )
        conn.close.assert_called_once()

    def test_inconsistent_publication_rejected(self):
        state = sample_state()
        state["published_content"] = None

        response, error, conn, _, _, _ = (
            self.invoke(state=state)
        )

        self.assertIsNone(response)
        self.assertIsInstance(
            error, InternalServerError
        )
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_invalid_stored_content_rejected(self):
        state = sample_state()
        state["published_content"] = {
            "hero": {}
        }

        response, error, conn, _, _, _ = (
            self.invoke(state=state)
        )

        self.assertIsNone(response)
        self.assertIsInstance(
            error, MarketingContentError
        )
        conn.close.assert_called_once()

    def test_database_failure_closes_connection(self):
        response, error, conn, _, _, _ = self.invoke(
            service_error=RuntimeError(
                "Simulated database failure"
            )
        )

        self.assertIsNone(response)
        self.assertIsInstance(
            error, RuntimeError
        )
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

    def test_local_response_is_private_and_uncached(self):
        response, error, _, _, _, _ = self.invoke()

        self.assertIsNone(error)
        self.assertIn(
            "no-store",
            response.headers["Cache-Control"],
        )
        self.assertIn(
            "noindex",
            response.headers["X-Robots-Tag"],
        )
        self.assertEqual(
            response.headers["Referrer-Policy"],
            "no-referrer",
        )

    def test_management_has_new_tab_shortcut(self):
        Environment().parse(self.editor)

        self.assertEqual(
            self.editor.count(
                "master_admin_website_home_published"
            ),
            1,
        )
        self.assertIn(
            "View Published Website",
            self.editor,
        )
        self.assertIn(
            'target="_blank"',
            self.editor,
        )
        self.assertIn(
            'rel="noopener noreferrer"',
            self.editor,
        )
        self.assertNotIn(
            "127.0.0.1:5056",
            self.editor,
        )


if __name__ == "__main__":
    unittest.main()
