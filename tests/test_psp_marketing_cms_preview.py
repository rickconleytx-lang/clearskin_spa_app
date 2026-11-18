import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from jinja2 import Environment
from werkzeug.exceptions import InternalServerError, abort


def saved_content():
    return {
        "hero": {
            "primary_button_text": "Start Your free trial today",
            "secondary_button_text": "View Pricing",
            "pricing_sentence": (
                "Solo is $49/month or $490/year "
                "after the 10-day free trial."
            ),
        },
    }


class FakeResponse:
    def __init__(self, body):
        self.body = body
        self.headers = {}


class MarketingCMSPreviewTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(Path("app.py").read_text())

        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "master_admin_website_home_preview"
        ]

        assert len(functions) == 1

        route = functions[0]

        cls.decorators = [
            ast.unparse(item)
            for item in route.decorator_list
        ]

        route.decorator_list = []

        cls.code = compile(
            ast.Module(body=[route], type_ignores=[]),
            "app.py",
            "exec",
        )

        cls.home = Path(
            "templates/public_site/psp_home.html"
        ).read_text()

        cls.editor = Path(
            "templates/master_admin_website_management.html"
        ).read_text()

    def run_preview(self, state=None, failure=None):
        conn = MagicMock()
        notices = []

        namespace = {
            "get_db_connection": lambda: conn,
            "render_template": (
                lambda name, **kwargs: (name, kwargs)
            ),
            "_public_security_csrf_token": (
                lambda purpose: "test-token"
            ),
            "url_for": (
                lambda endpoint: "/master-admin/website"
            ),
            "redirect": (
                lambda path: ("redirect", path)
            ),
            "flash": (
                lambda message, category:
                notices.append((message, category))
            ),
            "abort": abort,
        }

        exec(self.code, namespace)

        with patch(
            "services.psp_marketing_cms_service.load_home_state",
            return_value=state,
            side_effect=failure,
        ) as loader, patch(
            "flask.make_response",
            side_effect=lambda body: FakeResponse(body),
        ):
            try:
                response = namespace[
                    "master_admin_website_home_preview"
                ]()
                error = None
            except Exception as exc:
                response = None
                error = exc

            loader.assert_called_once_with(conn)

        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

        return response, error, notices

    def test_route_requires_master_admin(self):
        self.assertIn("login_required", self.decorators)
        self.assertIn(
            "master_admin_required", self.decorators
        )
        self.assertTrue(
            any(
                "/master-admin/website/home/preview" in item
                and "GET" in item
                for item in self.decorators
            )
        )

    def test_saved_draft_renders_actual_home_page(self):
        response, error, _ = self.run_preview({
            "draft_content": saved_content(),
        })

        self.assertIsNone(error)
        template, values = response.body

        self.assertEqual(
            template, "public_site/psp_home.html"
        )
        self.assertTrue(values["cms_preview"])
        self.assertEqual(
            values["cms_home_hero"]["primary_button_text"],
            "Start Your free trial today",
        )

    def test_preview_prevents_caching_and_indexing(self):
        response, error, _ = self.run_preview({
            "draft_content": saved_content(),
        })

        self.assertIsNone(error)
        self.assertIn(
            "no-store", response.headers["Cache-Control"]
        )
        self.assertIn(
            "noindex", response.headers["X-Robots-Tag"]
        )
        self.assertEqual(
            response.headers["Referrer-Policy"],
            "no-referrer",
        )

    def test_no_draft_redirects_to_editor(self):
        response, error, notices = self.run_preview({
            "draft_content": None,
        })

        self.assertIsNone(error)
        self.assertEqual(
            response,
            ("redirect", "/master-admin/website"),
        )
        self.assertEqual(notices[0][1], "error")

    def test_invalid_stored_draft_is_rejected(self):
        _, error, _ = self.run_preview({
            "draft_content": {"hero": {}},
        })

        self.assertIsInstance(
            error, InternalServerError
        )

    def test_database_failure_closes_connection(self):
        _, error, _ = self.run_preview(
            failure=RuntimeError("Simulated failure")
        )

        self.assertIsInstance(error, RuntimeError)

    def test_public_wording_and_private_preview(self):
        logo = self.home.index(
            '<div class="hero-logo-wrap">'
        )
        start = self.home.rfind(
            '<div class="hero-actions">', 0, logo
        )

        fragment = self.home[start:logo]
        template = Environment(
            autoescape=True
        ).from_string(fragment)

        public = template.render()

        self.assertIn(
            "Start Your 10-Day Free Trial", public
        )
        self.assertIn("View Pricing", public)
        self.assertIn(
            "Solo is $49/month or $490/year "
            "after the 10-day free trial.",
            public,
        )

        preview = template.render(
            cms_home_hero=saved_content()["hero"]
        )

        self.assertIn(
            "Start Your free trial today",
            preview,
        )
        self.assertNotIn(
            "Start Your 10-Day Free Trial",
            preview,
        )

    def test_preview_button_requires_saved_draft(self):
        start = self.editor.index(
            "{% if draft_revision_id is not none %}"
        )
        end = self.editor.index(
            "{% endif %}", start
        ) + len("{% endif %}")

        fragment = self.editor[start:end]

        template = Environment().from_string(fragment)

        context = {
            "url_for": lambda endpoint: (
                "/master-admin/website/home/preview"
            ),
        }

        self.assertNotIn(
            "Preview Draft",
            template.render(
                draft_revision_id=None,
                **context,
            ),
        )
        self.assertIn(
            "Preview Draft",
            template.render(
                draft_revision_id=1,
                **context,
            ),
        )



    def test_preview_banner_hidden_on_public_page(self):
        start = self.home.index(
            "{% if cms_preview | default(false) %}"
        )
        end = self.home.index(
            "{% endif %}", start
        ) + len("{% endif %}")

        fragment = self.home[start:end]

        template = Environment(
            autoescape=True
        ).from_string(fragment)

        url_for = lambda endpoint: (
            "/master-admin/website"
        )

        public = template.render(
            url_for=url_for
        )

        self.assertNotIn(
            "Draft Preview (Not Published)",
            public,
        )

        preview = template.render(
            cms_preview=True,
            url_for=url_for,
        )

        self.assertIn(
            "Draft Preview (Not Published)",
            preview,
        )
        self.assertIn(
            "Back to Website Management",
            preview,
        )
        self.assertIn(
            "/master-admin/website",
            preview,
        )

    def test_editor_correctly_describes_preview_status(self):
        self.assertIn(
            "Preview is available.",
            self.editor,
        )
        self.assertIn(
            "Publishing requires explicit confirmation on the review screen.",
            self.editor,
        )
        self.assertNotIn(
            "Preview and Publish are not enabled yet.",
            self.editor,
        )

if __name__ == "__main__":
    unittest.main()
