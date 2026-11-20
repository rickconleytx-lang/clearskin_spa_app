import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from werkzeug.exceptions import NotFound, abort

from services import psp_marketing_cms_showcase_preview as service


class FakeResponse:
    def __init__(self, body):
        self.body = body
        self.headers = {}


class ShowcasePreviewRouteTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = Path("app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        names = (
            "_master_admin_website_showcase_preview",
            "master_admin_website_peachweb_preview",
            "master_admin_website_peachbook_preview",
        )

        selected = []

        cls.decorators = {}

        for name in names:
            matches = [
                node for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.name == name
            ]

            assert len(matches) == 1, name

            node = matches[0]

            cls.decorators[name] = [
                ast.unparse(item)
                for item in node.decorator_list
            ]

            node.decorator_list = []
            selected.append(node)

        cls.code = compile(
            ast.Module(body=selected, type_ignores=[]),
            "app.py",
            "exec",
        )

    def run_preview(
        self,
        showcase,
        *,
        context=None,
        missing=False,
        failure=None,
        render_failure=None,
    ):
        conn = MagicMock()
        notices = []

        if context is None and not missing:
            context = {
                "cms_preview": True,
                f"cms_{showcase}_showcase": {
                    "image_url": (
                        f"https://example.test/{showcase}.png"
                    ),
                    "image_alt": f"{showcase} preview picture",
                    "caption": f"{showcase} private caption",
                },
            }

        def render(name, **values):
            if render_failure is not None:
                raise render_failure
            return (name, values)

        namespace = {
            "get_db_connection": lambda: conn,
            "render_template": render,
            "abort": abort,
            "flash": (
                lambda message, category:
                notices.append((message, category))
            ),
            "redirect": lambda path: ("redirect", path),
            "url_for": lambda endpoint: "/" + endpoint,
            "_public_security_csrf_token": (
                lambda purpose: "private-test-token"
            ),
        }

        exec(self.code, namespace)

        function_name = (
            f"master_admin_website_{showcase}_preview"
        )

        with (
            patch.object(
                service,
                "build_showcase_preview_context",
                return_value=None if missing else context,
                side_effect=failure,
            ) as builder,
            patch(
                "flask.make_response",
                side_effect=FakeResponse,
            ),
        ):
            try:
                response = namespace[function_name]()
                error = None
            except Exception as exc:
                response = None
                error = exc

        return response, error, conn, builder, notices

    def test_both_get_routes_require_master_admin(self):
        for showcase in ("peachweb", "peachbook"):
            with self.subTest(showcase=showcase):
                name = (
                    f"master_admin_website_{showcase}_preview"
                )

                decorators = self.decorators[name]

                self.assertIn(
                    "login_required",
                    decorators,
                )
                self.assertIn(
                    "master_admin_required",
                    decorators,
                )
                self.assertTrue(
                    any(
                        f"/home/{showcase}/preview" in item
                        and "GET" in item
                        for item in decorators
                    )
                )

    def test_peachweb_renders_private_homepage_preview(self):
        response, error, conn, builder, _ = (
            self.run_preview("peachweb")
        )

        self.assertIsNone(error)
        name, values = response.body

        self.assertEqual(name, "public_site/psp_home.html")
        self.assertTrue(values["cms_preview"])
        self.assertIn("cms_peachweb_showcase", values)
        self.assertNotIn("cms_peachbook_showcase", values)
        self.assertEqual(
            values["contact_csrf_token"],
            "private-test-token",
        )

        self.assertEqual(
            builder.call_args.kwargs["showcase"],
            "peachweb",
        )
        builder.assert_called_once()
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_peachbook_renders_private_homepage_preview(self):
        response, error, conn, builder, _ = (
            self.run_preview("peachbook")
        )

        self.assertIsNone(error)
        name, values = response.body

        self.assertEqual(name, "public_site/psp_home.html")
        self.assertIn("cms_peachbook_showcase", values)
        self.assertNotIn("cms_peachweb_showcase", values)

        self.assertEqual(
            builder.call_args.kwargs["showcase"],
            "peachbook",
        )
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_both_responses_are_private(self):
        for showcase in ("peachweb", "peachbook"):
            with self.subTest(showcase=showcase):
                response, error, _, _, _ = (
                    self.run_preview(showcase)
                )

                self.assertIsNone(error)
                self.assertIn(
                    "no-store",
                    response.headers["Cache-Control"],
                )
                self.assertIn(
                    "private",
                    response.headers["Cache-Control"],
                )
                self.assertEqual(
                    response.headers["X-Robots-Tag"],
                    "noindex, nofollow",
                )
                self.assertEqual(
                    response.headers["Referrer-Policy"],
                    "no-referrer",
                )

    def test_missing_peachweb_draft_redirects_to_editor(self):
        response, error, conn, _, notices = (
            self.run_preview("peachweb", missing=True)
        )

        self.assertIsNone(error)
        self.assertEqual(
            response,
            (
                "redirect",
                "/master_admin_website_peachweb_editor",
            ),
        )
        self.assertEqual(notices[0][1], "error")
        conn.close.assert_called_once()

    def test_missing_peachbook_draft_redirects_to_editor(self):
        response, error, conn, _, notices = (
            self.run_preview("peachbook", missing=True)
        )

        self.assertIsNone(error)
        self.assertEqual(
            response,
            (
                "redirect",
                "/master_admin_website_peachbook_editor",
            ),
        )
        self.assertEqual(notices[0][1], "error")
        conn.close.assert_called_once()

    def test_database_error_rolls_back_and_closes(self):
        _, error, conn, _, _ = self.run_preview(
            "peachweb",
            failure=RuntimeError("Simulated database failure"),
        )

        self.assertIsInstance(error, RuntimeError)
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

    def test_invalid_preview_content_closes_connection(self):
        _, error, conn, _, _ = self.run_preview(
            "peachbook",
            failure=ValueError("Invalid saved content"),
        )

        self.assertIsInstance(error, ValueError)
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_rendering_error_occurs_after_connection_cleanup(self):
        _, error, conn, _, _ = self.run_preview(
            "peachweb",
            render_failure=RuntimeError(
                "Simulated template failure"
            ),
        )

        self.assertIsInstance(error, RuntimeError)
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

    def test_routes_do_not_publish_or_commit(self):
        for showcase in ("peachweb", "peachbook"):
            with self.subTest(showcase=showcase):
                _, error, conn, _, _ = (
                    self.run_preview(showcase)
                )

                self.assertIsNone(error)
                conn.commit.assert_not_called()

        source = Path("app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        names = {
            "_master_admin_website_showcase_preview",
            "master_admin_website_peachweb_preview",
            "master_admin_website_peachbook_preview",
        }

        for node in tree.body:
            if (
                isinstance(node, ast.FunctionDef)
                and node.name in names
            ):
                body = ast.unparse(node)

                self.assertNotIn(
                    "publish_showcase_draft",
                    body,
                )
                self.assertNotIn(
                    "connection.commit(",
                    body,
                )


if __name__ == "__main__":
    unittest.main()
