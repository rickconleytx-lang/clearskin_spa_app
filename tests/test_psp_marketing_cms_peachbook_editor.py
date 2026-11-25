import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.psp_marketing_cms_content import (
    MarketingContentError,
)


def valid_content(caption="Example caption"):
    return {
        "showcase": {
            "image_public_id": "",
            "image_url": "",
            "image_alt": "",
            "caption": caption,
        }
    }


class PeachBookEditorRouteTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = Path("app.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)

        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "master_admin_website_peachbook_editor"
        ]

        assert len(matches) == 1
        route = matches[0]

        decorators = [
            ast.unparse(item)
            for item in route.decorator_list
        ]

        assert "login_required" in decorators
        assert "master_admin_required" in decorators
        assert any(
            "/master-admin/website/home/peachbook" in item
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
                        "master_admin_website_peachbook_editor"
                    ]()
                result = None
            else:
                result = namespace[
                    "master_admin_website_peachbook_editor"
                ]()

            loader.assert_called_once_with(
                conn,
                section_key="home.peachbook",
            )

        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

        return result

    def test_first_edit_uses_existing_illustration(self):
        result = self.invoke()

        self.assertEqual(
            result["template"],
            "master_admin_website_peachbook.html",
        )
        self.assertEqual(
            result["showcase"]["image_url"], ""
        )
        self.assertEqual(
            result["content_source"],
            "existing website illustration",
        )

    def test_saved_draft_takes_precedence(self):
        result = self.invoke({
            "draft_revision_id": 601,
            "draft_content": valid_content("Saved caption"),
            "published_content": valid_content(
                "Published caption"
            ),
        })

        self.assertEqual(
            result["showcase"]["caption"],
            "Saved caption",
        )
        self.assertEqual(
            result["draft_revision_id"], 601
        )
        self.assertEqual(
            result["content_source"], "saved draft"
        )

    def test_published_content_used_without_draft(self):
        result = self.invoke({
            "draft_revision_id": None,
            "draft_content": None,
            "published_content": valid_content(
                "Published caption"
            ),
        })

        self.assertEqual(
            result["showcase"]["caption"],
            "Published caption",
        )
        self.assertEqual(
            result["content_source"], "published content"
        )

    def test_multiline_caption_is_preserved(self):
        result = self.invoke({
            "draft_revision_id": 601,
            "draft_content": valid_content(
                "First line\nSecond line"
            ),
            "published_content": None,
        })

        self.assertEqual(
            result["showcase"]["caption"].count("\n"),
            1,
        )

    def test_invalid_stored_content_is_rejected(self):
        with self.assertRaises(MarketingContentError):
            self.invoke({
                "draft_revision_id": 601,
                "draft_content": {
                    "showcase": {
                        "caption": "<script>bad</script>"
                    }
                },
                "published_content": None,
            })

    def test_database_error_closes_connection(self):
        self.invoke(
            error=RuntimeError("Database failure")
        )

    def test_editor_is_read_only(self):
        self.assertIn(
            'section_key="home.peachbook"',
            self.route_source,
        )
        self.assertNotIn(
            "save_section_draft(",
            self.route_source,
        )
        self.assertNotIn(
            "upload_showcase_image(",
            self.route_source,
        )
        self.assertNotIn(
            "publish_home_draft(",
            self.route_source,
        )
        self.assertNotIn(
            "conn.commit()",
            self.route_source,
        )


if __name__ == "__main__":
    unittest.main()
