import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.psp_marketing_cms_media import (
    MarketingCMSImageError,
)
from services.psp_marketing_cms_service import (
    MarketingCMSConfigurationError,
)


class Aborted(Exception):
    def __init__(self, code):
        self.code = code


PUBLIC_ID = (
    "peach-suite-pro/marketing-cms/showcases/"
    "peachweb/" + "a" * 32
)
IMAGE_URL = (
    "https://res.cloudinary.com/example/image/upload/"
    f"v1234567890/{PUBLIC_ID}.png"
)


class PeachWebUploadRouteTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = Path("app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "master_admin_website_peachweb_save_draft"
        ]
        assert len(matches) == 1

        route = matches[0]
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

    def invoke(
        self,
        *,
        form=None,
        files=None,
        revision=21,
        configured=True,
        upload_error=None,
        state=None,
        autocommit=False,
    ):
        if form is None:
            form = {
                "security_csrf_token": "valid",
                "expected_draft_revision_id": "21",
                "caption": "First line\nSecond line",
                "image_alt": "Customer PeachWeb homepage",
            }

        if files is None:
            files = {
                "showcase_image": SimpleNamespace(
                    filename="website.png"
                )
            }

        if state is None:
            state = {
                "draft_revision_id": 21,
                "draft_content": {
                    "showcase": {
                        "image_public_id": "",
                        "image_url": "",
                        "image_alt": "",
                        "caption": "Old caption",
                    }
                },
                "published_content": None,
            }

        self.conn = MagicMock()
        self.conn.autocommit = autocommit
        cursor = (
            self.conn.cursor.return_value
            .__enter__.return_value
        )
        cursor.fetchone.return_value = (revision,)
        self.cursor = cursor
        self.database = MagicMock(return_value=self.conn)
        self.messages = []

        def abort(code):
            raise Aborted(code)

        namespace = {
            "request": SimpleNamespace(
                form=form,
                files=files,
            ),
            "session": {"user_id": 7},
            "_security_form_csrf_valid": (
                lambda value: value == "valid"
            ),
            "CLOUDINARY_CONFIGURED": configured,
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
            "services.psp_marketing_cms_service."
            "load_section_state",
            return_value=state,
        ) as loader, patch(
            "services.psp_marketing_cms_service."
            "save_section_draft",
            return_value={"revision_number": 2},
        ) as saver, patch(
            "services.psp_marketing_cms_cloudinary."
            "upload_showcase_image",
            return_value={
                "public_id": PUBLIC_ID,
                "secure_url": IMAGE_URL,
            },
            side_effect=upload_error,
        ) as uploader:
            self.loader = loader
            self.saver = saver
            self.uploader = uploader

            try:
                result = namespace[
                    "master_admin_website_peachweb_save_draft"
                ]()
            finally:
                if self.database.called:
                    self.conn.close.assert_called_once()

        return result

    def test_upload_saves_trusted_asset_and_caption(self):
        file = SimpleNamespace(filename="example.png")

        result = self.invoke(files={"showcase_image": file})

        content = self.saver.call_args.kwargs["content"]
        saved = content["showcase"]

        self.assertEqual(saved["image_public_id"], PUBLIC_ID)
        self.assertEqual(saved["image_url"], IMAGE_URL)
        self.assertEqual(
            saved["image_alt"],
            "Customer PeachWeb homepage",
        )
        self.assertEqual(
            saved["caption"],
            "First line\nSecond line",
        )
        self.assertEqual(
            self.saver.call_args.kwargs["section_key"],
            "home.peachweb",
        )
        self.uploader.assert_called_once_with(
            file, "peachweb"
        )
        self.assertIn("FOR UPDATE",
                      self.cursor.execute.call_args.args[0])
        self.assertEqual(self.messages[-1][1], "success")
        self.assertIn("redirect", result)

    def test_stale_revision_prevents_cloudinary_upload(self):
        self.invoke(revision=22)

        self.uploader.assert_not_called()
        self.saver.assert_not_called()
        self.loader.assert_not_called()
        self.assertEqual(self.messages[-1][1], "error")

    def test_missing_alt_prevents_upload(self):
        form = {
            "security_csrf_token": "valid",
            "expected_draft_revision_id": "21",
            "caption": "Valid caption",
            "image_alt": "",
        }
        self.invoke(form=form)

        self.uploader.assert_not_called()
        self.saver.assert_not_called()
        self.assertEqual(self.messages[-1][1], "error")

    def test_bad_caption_prevents_upload(self):
        form = {
            "security_csrf_token": "valid",
            "expected_draft_revision_id": "21",
            "caption": "<script>invalid</script>",
            "image_alt": "Website screenshot",
        }
        self.invoke(form=form)

        self.uploader.assert_not_called()
        self.saver.assert_not_called()
        self.assertEqual(self.messages[-1][1], "error")

    def test_invalid_image_never_saves_draft(self):
        self.invoke(
            upload_error=MarketingCMSImageError(
                "Only PNG and JPEG screenshots are supported."
            )
        )

        self.uploader.assert_called_once()
        self.saver.assert_not_called()
        self.assertEqual(self.messages[-1][1], "error")

    def test_storage_failure_never_saves_draft(self):
        with patch("logging.exception"):
            self.invoke(
                upload_error=RuntimeError(
                    "Simulated Cloudinary failure"
                )
            )

        self.uploader.assert_called_once()
        self.saver.assert_not_called()
        self.assertEqual(self.messages[-1][1], "error")

    def test_missing_cloudinary_configuration(self):
        self.invoke(configured=False)

        self.database.assert_not_called()
        self.uploader.assert_not_called()
        self.saver.assert_not_called()
        self.assertEqual(self.messages[-1][1], "error")

    def test_unexpected_file_field_rejected(self):
        with self.assertRaises(Aborted) as raised:
            self.invoke(files={
                "unexpected_file": SimpleNamespace(
                    filename="other.png"
                )
            })

        self.assertEqual(raised.exception.code, 400)
        self.database.assert_not_called()

    def test_edit_existing_alt_without_upload(self):
        state = {
            "draft_revision_id": 21,
            "draft_content": {
                "showcase": {
                    "image_public_id": PUBLIC_ID,
                    "image_url": IMAGE_URL,
                    "image_alt": "Old description",
                    "caption": "Old caption",
                }
            },
            "published_content": None,
        }

        self.invoke(
            files={},
            state=state,
        )

        saved = (
            self.saver.call_args.kwargs["content"]["showcase"]
        )
        self.assertEqual(
            saved["image_alt"],
            "Customer PeachWeb homepage",
        )
        self.assertEqual(saved["image_public_id"], PUBLIC_ID)
        self.assertEqual(saved["image_url"], IMAGE_URL)
        self.uploader.assert_not_called()
        self.cursor.execute.assert_not_called()

    def test_failed_upload_explicitly_rolls_back(self):
        self.invoke(
            upload_error=MarketingCMSImageError(
                "Simulated invalid image"
            )
        )

        self.uploader.assert_called_once()
        self.saver.assert_not_called()
        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_success_does_not_rollback_saved_draft(self):
        self.invoke()

        self.saver.assert_called_once()
        self.conn.rollback.assert_not_called()
        self.conn.close.assert_called_once()

    def test_autocommit_prevents_upload(self):
        with self.assertRaises(
            MarketingCMSConfigurationError
        ):
            self.invoke(autocommit=True)

        self.uploader.assert_not_called()
        self.saver.assert_not_called()


if __name__ == "__main__":
    unittest.main()
