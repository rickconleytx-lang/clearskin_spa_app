import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class MarketingCMSHomeLoadingTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(
            Path("app.py").read_text(encoding="utf-8")
        )

        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "master_admin_website_management"
        ]

        assert len(matches) == 1

        route = matches[0]
        route.decorator_list = []

        cls.route_code = compile(
            ast.Module(
                body=[route],
                type_ignores=[],
            ),
            "app.py",
            "exec",
        )

    def invoke_route(self, state=None, error=None):
        conn = MagicMock()

        if state is not None:
            state = {
                "draft_revision_id": None,
                **state,
            }

        namespace = {
            "_security_form_csrf_token": (
                lambda: "unit-test-token"
            ),
            "get_db_connection": lambda: conn,
            "render_template": (
                lambda name, **kwargs: {
                    "template": name,
                    **kwargs,
                }
            ),
        }

        exec(self.route_code, namespace)

        with patch(
            "services.psp_marketing_cms_service."
            "load_home_state",
            return_value=state,
            side_effect=error,
        ) as loader:
            if error is not None:
                with self.assertRaises(RuntimeError):
                    namespace[
                        "master_admin_website_management"
                    ]()
                result = None
            else:
                result = namespace[
                    "master_admin_website_management"
                ]()

            loader.assert_called_once_with(conn)

        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

        return result

    def test_no_revision_uses_existing_website_wording(self):
        result = self.invoke_route({
            "draft_content": None,
            "published_content": None,
        })

        self.assertEqual(
            result["home_hero"]["primary_button_text"],
            "Start Your 10-Day Free Trial",
        )
        self.assertEqual(
            result["content_source"],
            "existing website wording",
        )

    def test_saved_draft_takes_precedence(self):
        result = self.invoke_route({
            "draft_content": {
                "hero": {
                    "primary_button_text": "Draft",
                },
            },
            "published_content": {
                "hero": {
                    "primary_button_text": "Published",
                },
            },
        })

        self.assertEqual(
            result["home_hero"]["primary_button_text"],
            "Draft",
        )
        self.assertEqual(
            result["content_source"],
            "saved draft",
        )

    def test_published_content_used_without_draft(self):
        result = self.invoke_route({
            "draft_content": None,
            "published_content": {
                "hero": {
                    "primary_button_text": "Published",
                },
            },
        })

        self.assertEqual(
            result["home_hero"]["primary_button_text"],
            "Published",
        )
        self.assertEqual(
            result["content_source"],
            "published content",
        )

    def test_connection_closed_after_database_error(self):
        self.invoke_route(
            error=RuntimeError("Simulated database error")
        )


    def test_form_receives_revision_and_csrf_token(self):
        result = self.invoke_route({
            "draft_revision_id": 42,
            "draft_content": None,
            "published_content": None,
        })

        self.assertEqual(result["draft_revision_id"], 42)
        self.assertEqual(
            result["security_csrf_token"],
            "unit-test-token",
        )


if __name__ == "__main__":
    unittest.main()
