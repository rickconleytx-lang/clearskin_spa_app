import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.psp_marketing_cms_content import (
    MarketingContentError,
)


def valid_content(headline="Draft headline"):
    return {
        "promotion": {
            "product_label": "Solo",
            "headline": headline,
            "monthly_price": "$49",
            "pricing_description": "Example description.",
            "features": [
                f"Feature {index}"
                for index in range(1, 10)
            ],
        }
    }


class MarketingCMSPromotionEditorTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = Path("app.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)

        routes = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == (
                "master_admin_website_promotion_editor"
            )
        ]

        assert len(routes) == 1
        route = routes[0]

        decorators = [
            ast.unparse(item)
            for item in route.decorator_list
        ]

        assert "login_required" in decorators
        assert "master_admin_required" in decorators

        assert any(
            "/master-admin/website/home/promotion" in item
            for item in decorators
        )

        cls.route_source = ast.get_source_segment(
            source, route
        )

        route.decorator_list = []

        cls.route_code = compile(
            ast.Module(
                body=[route],
                type_ignores=[],
            ),
            "app.py",
            "exec",
        )

    def invoke(self, state=None, error=None):
        conn = MagicMock()
        factory = MagicMock(return_value=conn)

        if state is None:
            state = {
                "draft_revision_id": None,
                "draft_content": None,
                "published_content": None,
            }

        namespace = {
            "get_db_connection": factory,
            "_security_form_csrf_token": (
                lambda: "test-token"
            ),
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
            "load_section_state",
            return_value=state,
            side_effect=error,
        ) as loader:
            if error is not None:
                with self.assertRaises(RuntimeError):
                    namespace[
                        "master_admin_website_promotion_editor"
                    ]()
                result = None
            else:
                result = namespace[
                    "master_admin_website_promotion_editor"
                ]()

            loader.assert_called_once_with(
                conn,
                section_key="home.promo",
            )

        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

        return result

    def test_first_edit_uses_existing_website_wording(self):
        result = self.invoke()

        self.assertEqual(
            result["template"],
            "master_admin_website_promotion.html",
        )
        self.assertEqual(
            result["promotion"]["product_label"],
            "Solo",
        )
        self.assertEqual(
            result["promotion"]["monthly_price"],
            "$49",
        )
        self.assertEqual(
            len(result["promotion"]["features"]), 9
        )
        self.assertEqual(
            result["content_source"],
            "existing website wording",
        )

    def test_saved_draft_takes_precedence(self):
        result = self.invoke({
            "draft_revision_id": 501,
            "draft_content": valid_content(
                "Saved draft"
            ),
            "published_content": valid_content(
                "Published version"
            ),
        })

        self.assertEqual(
            result["promotion"]["headline"],
            "Saved draft",
        )
        self.assertEqual(
            result["content_source"],
            "saved draft",
        )
        self.assertEqual(
            result["draft_revision_id"], 501
        )

    def test_published_content_used_without_draft(self):
        result = self.invoke({
            "draft_revision_id": None,
            "draft_content": None,
            "published_content": valid_content(
                "Published version"
            ),
        })

        self.assertEqual(
            result["promotion"]["headline"],
            "Published version",
        )
        self.assertEqual(
            result["content_source"],
            "published content",
        )

    def test_actual_manual_line_breaks_preserved(self):
        result = self.invoke({
            "draft_revision_id": 501,
            "draft_content": valid_content(
                "One business.\nOne owner.\n"
                "One connected system."
            ),
            "published_content": None,
        })

        self.assertEqual(
            result["promotion"]["headline"].count("\n"),
            2,
        )

    def test_invalid_stored_content_not_silently_used(self):
        with self.assertRaises(MarketingContentError):
            self.invoke({
                "draft_revision_id": 501,
                "draft_content": {
                    "promotion": {
                        "headline": "<script>bad</script>"
                    }
                },
                "published_content": None,
            })

    def test_database_error_closes_connection(self):
        self.invoke(
            error=RuntimeError("Database failure")
        )

    def test_route_has_no_write_or_publish_operation(self):
        self.assertIn(
            'section_key="home.promo"',
            self.route_source,
        )
        self.assertNotIn(
            "save_section_draft(",
            self.route_source,
        )
        self.assertNotIn(
            "publish_home_draft(",
            self.route_source,
        )
        self.assertNotIn(
            "connection.commit()",
            self.route_source,
        )


if __name__ == "__main__":
    unittest.main()
