import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.psp_marketing_cms_content import MarketingContentError
from services.psp_marketing_cms_service import MarketingCMSConflict


class Aborted(Exception):
    def __init__(self, code):
        self.code = code


class PeachBookSaveRouteTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = Path("app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "master_admin_website_peachbook_save_draft"
        ]
        assert len(matches) == 1

        route = matches[0]
        cls.decorators = [
            ast.unparse(item) for item in route.decorator_list
        ]
        cls.route_source = ast.get_source_segment(source, route)

        route.decorator_list = []
        cls.code = compile(
            ast.Module(body=[route], type_ignores=[]),
            "app.py",
            "exec",
        )

    def invoke(
        self,
        *,
        form=None,
        state=None,
        actor=7,
        csrf=True,
        save_error=None,
        load_error=None,
    ):
        if form is None:
            form = {
                "security_csrf_token": "valid",
                "expected_draft_revision_id": "",
                "caption": "First line\nSecond line",
            }

        default_state = {
            "draft_revision_id": None,
            "draft_content": None,
            "published_content": None,
        }
        if state:
            default_state.update(state)

        self.conn = MagicMock()
        self.database = MagicMock(return_value=self.conn)
        self.messages = []

        def abort(code):
            raise Aborted(code)

        namespace = {
            "request": MagicMock(form=form),
            "session": {"user_id": actor},
            "_security_form_csrf_valid": (
                lambda value: csrf and value == "valid"
            ),
            "get_db_connection": self.database,
            "abort": abort,
            "flash": lambda message, category: (
                self.messages.append((message, category))
            ),
            "url_for": lambda endpoint: "/" + endpoint,
            "redirect": lambda url: {"redirect": url},
        }

        exec(self.code, namespace)

        with patch(
            "services.psp_marketing_cms_service.load_section_state",
            return_value=default_state,
            side_effect=load_error,
        ) as loader, patch(
            "services.psp_marketing_cms_service.save_section_draft",
            return_value={"revision_number": 2},
            side_effect=save_error,
        ) as saver:
            self.loader = loader
            self.saver = saver

            try:
                return namespace[
                    "master_admin_website_peachbook_save_draft"
                ]()
            finally:
                if self.database.called:
                    self.conn.close.assert_called_once()

    def test_first_caption_save(self):
        result = self.invoke()

        arguments = self.saver.call_args.kwargs

        self.assertEqual(arguments["section_key"], "home.peachbook")
        self.assertEqual(arguments["actor_id"], 7)
        self.assertIsNone(arguments["expected_draft_revision_id"])
        self.assertEqual(
            arguments["content"]["showcase"]["caption"],
            "First line\nSecond line",
        )
        self.assertEqual(
            arguments["content"]["showcase"]["image_url"], ""
        )
        self.assertIn("redirect", result)
        self.assertEqual(self.messages[-1][1], "success")

    def test_saved_image_reference_is_preserved(self):
        public_id = (
            "peach-suite-pro/marketing-cms/showcases/"
            "peachbook/" + "a" * 32
        )
        showcase = {
            "image_public_id": public_id,
            "image_url": (
                "https://res.cloudinary.com/example/image/upload/"
                f"v1234567890/{public_id}.png"
            ),
            "image_alt": "Customer website screenshot",
            "caption": "Old caption",
        }

        self.invoke(
            form={
                "security_csrf_token": "valid",
                "expected_draft_revision_id": "51",
                "caption": "Updated caption",
            },
            state={
                "draft_revision_id": 51,
                "draft_content": {"showcase": showcase},
            },
        )

        arguments = self.saver.call_args.kwargs
        saved = arguments["content"]["showcase"]

        self.assertEqual(saved["image_public_id"], public_id)
        self.assertEqual(saved["image_url"], showcase["image_url"])
        self.assertEqual(saved["image_alt"], showcase["image_alt"])
        self.assertEqual(saved["caption"], "Updated caption")
        self.assertEqual(showcase["caption"], "Old caption")
        self.assertEqual(
            arguments["expected_draft_revision_id"], 51
        )

    def test_uses_published_content_when_no_draft(self):
        self.invoke(state={
            "draft_content": None,
            "published_content": {
                "showcase": {
                    "image_public_id": "",
                    "image_url": "",
                    "image_alt": "",
                    "caption": "Previously published",
                }
            },
        })

        self.saver.assert_called_once()
        self.assertEqual(
            self.saver.call_args.kwargs["content"]
            ["showcase"]["caption"],
            "First line\nSecond line",
        )

    def test_rejects_browser_image_metadata(self):
        with self.assertRaises(Aborted) as raised:
            self.invoke(form={
                "security_csrf_token": "valid",
                "expected_draft_revision_id": "",
                "caption": "Test",
                "image_url": "https://example.com/untrusted.png",
            })

        self.assertEqual(raised.exception.code, 400)
        self.database.assert_not_called()

    def test_rejects_missing_csrf(self):
        with self.assertRaises(Aborted) as raised:
            self.invoke(csrf=False)

        self.assertEqual(raised.exception.code, 400)
        self.database.assert_not_called()

    def test_rejects_invalid_actor(self):
        with self.assertRaises(Aborted) as raised:
            self.invoke(actor=0)

        self.assertEqual(raised.exception.code, 403)
        self.database.assert_not_called()

    def test_rejects_invalid_revision(self):
        with self.assertRaises(Aborted) as raised:
            self.invoke(form={
                "security_csrf_token": "valid",
                "expected_draft_revision_id": "not-a-number",
                "caption": "Test",
            })

        self.assertEqual(raised.exception.code, 400)
        self.database.assert_not_called()

    def test_stale_draft_conflict(self):
        self.invoke(
            save_error=MarketingCMSConflict("Stale revision")
        )

        self.assertEqual(self.messages[-1][1], "error")
        self.assertIn(
            "Reload", self.messages[-1][0]
        )

    def test_invalid_caption(self):
        self.invoke(
            save_error=MarketingContentError("Invalid caption")
        )

        self.assertEqual(self.messages[-1][1], "error")

    def test_database_failure_closes_connection(self):
        with self.assertRaises(RuntimeError):
            self.invoke(
                load_error=RuntimeError("Database unavailable")
            )

        self.conn.close.assert_called_once()

    def test_route_authorization_and_no_publication(self):
        self.assertIn("login_required", self.decorators)
        self.assertIn("master_admin_required", self.decorators)
        self.assertTrue(any(
            "/master-admin/website/home/peachbook/save" in item
            and "POST" in item
            for item in self.decorators
        ))
        self.assertIn(
            "upload_showcase_image(", self.route_source
        )
        self.assertIn(
            "if has_upload:", self.route_source
        )
        self.assertNotIn(
            "publish_section", self.route_source
        )
        self.assertNotIn(
            "published_revision_id", self.route_source
        )



class PeachBookCaptionStageGuards(unittest.TestCase):

    def test_peachbook_upload_uses_protected_cloudinary_path(self):
        import ast
        from pathlib import Path

        source = Path("app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "master_admin_website_peachbook_save_draft"
        ]

        self.assertEqual(len(matches), 1)
        body = ast.get_source_segment(source, matches[0])

        self.assertIn("CLOUDINARY_CONFIGURED", body)
        self.assertIn("FOR UPDATE", body)
        self.assertIn("upload_showcase_image(", body)
        self.assertIn('"peachbook",', body)
        self.assertIn(
            'section_key="home.peachbook"',
            body,
        )
        self.assertLess(
            body.index("FOR UPDATE"),
            body.index("upload_showcase_image("),
        )
        self.assertNotIn(
            "if has_upload:\n        abort(400)",
            body,
        )

    def test_peachbook_stays_separate_from_peachweb(self):
        from pathlib import Path

        source = Path("app.py").read_text(encoding="utf-8")

        self.assertEqual(
            source.count(
                "def master_admin_website_peachbook_save_draft("
            ),
            1,
        )
        self.assertEqual(
            source.count(
                "def master_admin_website_peachweb_save_draft("
            ),
            1,
        )
        self.assertIn(
            'section_key="home.peachbook"',
            source,
        )


if __name__ == "__main__":
    unittest.main()
