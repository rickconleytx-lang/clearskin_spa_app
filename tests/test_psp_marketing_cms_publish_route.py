import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from werkzeug.exceptions import (
    BadRequest,
    Forbidden,
    abort,
)

from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
)


class MarketingCMSPublishRouteTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = Path("app.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)

        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == (
                "master_admin_website_publish_draft"
            )
        ]

        assert len(functions) == 1

        route = functions[0]

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
        *,
        form_changes=None,
        missing_fields=(),
        actor="7",
        service_error=None,
    ):
        form = {
            "security_csrf_token": "valid-token",
            "publish_confirmation": "PUBLISH",
            "expected_draft_revision_id": "42",
            "expected_published_revision_id": "",
        }

        if form_changes:
            form.update(form_changes)

        for field in missing_fields:
            form.pop(field, None)

        connection = MagicMock()
        connection_factory = MagicMock(
            return_value=connection
        )
        messages = []

        namespace = {
            "request": SimpleNamespace(form=form),
            "session": {"user_id": actor},
            "_security_form_csrf_valid": (
                lambda token: token == "valid-token"
            ),
            "get_db_connection": connection_factory,
            "flash": (
                lambda message, category:
                messages.append((message, category))
            ),
            "redirect": (
                lambda path: ("redirect", path)
            ),
            "url_for": (
                lambda endpoint:
                "/master-admin/website"
            ),
            "abort": abort,
        }

        exec(self.code, namespace)

        with patch(
            "services.psp_marketing_cms_publication."
            "publish_home_draft",
            return_value={
                "revision_id": 42,
                "publication_event_id": 9,
            },
            side_effect=service_error,
        ) as publisher:
            try:
                response = namespace[
                    "master_admin_website_publish_draft"
                ]()
                failure = None

            except Exception as exc:
                response = None
                failure = exc

            calls = list(publisher.call_args_list)

        return (
            response,
            failure,
            calls,
            connection,
            connection_factory,
            messages,
        )

    def test_route_is_post_only_and_master_admin(self):
        self.assertIn(
            "login_required",
            self.decorators,
        )
        self.assertIn(
            "master_admin_required",
            self.decorators,
        )
        self.assertTrue(
            any(
                "/master-admin/website/home/publish"
                in item
                and "POST" in item
                for item in self.decorators
            )
        )
        self.assertNotIn(
            "master_admin_website_publish_draft",
            self.editor,
        )

    def test_first_publication_uses_expected_revisions(self):
        response, failure, calls, conn, _, notices = (
            self.invoke()
        )

        self.assertIsNone(failure)
        self.assertEqual(
            response,
            ("redirect", "/master-admin/website"),
        )
        self.assertEqual(len(calls), 1)

        args, kwargs = calls[0]
        self.assertEqual(args, (conn,))
        self.assertEqual(kwargs, {
            "actor_id": 7,
            "expected_draft_revision_id": 42,
            "expected_published_revision_id": None,
        })

        conn.close.assert_called_once()
        conn.commit.assert_not_called()
        self.assertEqual(notices[0][1], "success")
        self.assertIn("42", notices[0][0])

    def test_existing_publication_id_is_passed(self):
        _, failure, calls, conn, _, _ = self.invoke(
            form_changes={
                "expected_published_revision_id": "31",
            }
        )

        self.assertIsNone(failure)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0].kwargs[
                "expected_published_revision_id"
            ],
            31,
        )
        conn.close.assert_called_once()

    def test_bad_csrf_is_rejected_before_database(self):
        _, error, calls, _, factory, _ = self.invoke(
            form_changes={
                "security_csrf_token": "invalid",
            }
        )

        self.assertIsInstance(error, BadRequest)
        self.assertEqual(calls, [])
        factory.assert_not_called()

    def test_missing_confirmation_is_rejected(self):
        _, error, calls, _, factory, _ = self.invoke(
            form_changes={
                "publish_confirmation": "not yet",
            }
        )

        self.assertIsInstance(error, BadRequest)
        self.assertEqual(calls, [])
        factory.assert_not_called()

    def test_bad_actor_is_rejected(self):
        _, error, calls, _, factory, _ = self.invoke(
            actor=False
        )

        self.assertIsInstance(error, Forbidden)
        self.assertEqual(calls, [])
        factory.assert_not_called()

    def test_invalid_draft_revision_is_rejected(self):
        for value in ("", "0", "abc", "-1"):
            with self.subTest(value=value):
                _, error, calls, _, factory, _ = (
                    self.invoke(
                        form_changes={
                            "expected_draft_revision_id": value,
                        }
                    )
                )

                self.assertIsInstance(error, BadRequest)
                self.assertEqual(calls, [])
                factory.assert_not_called()

    def test_invalid_published_revision_is_rejected(self):
        for value in ("abc", "-1", "0"):
            with self.subTest(value=value):
                _, error, calls, _, factory, _ = (
                    self.invoke(
                        form_changes={
                            "expected_published_revision_id": value,
                        }
                    )
                )

                self.assertIsInstance(error, BadRequest)
                self.assertEqual(calls, [])
                factory.assert_not_called()

    def test_stale_revision_reports_error(self):
        response, error, calls, conn, _, notices = (
            self.invoke(
                service_error=MarketingCMSConflict(
                    "Simulated stale revision"
                )
            )
        )

        self.assertIsNone(error)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            response,
            ("redirect", "/master-admin/website"),
        )
        self.assertEqual(notices[0][1], "error")
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

    def test_unexpected_failure_closes_connection(self):
        _, error, calls, conn, _, notices = (
            self.invoke(
                service_error=RuntimeError(
                    "Simulated database failure"
                )
            )
        )

        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(len(calls), 1)
        self.assertEqual(notices, [])
        conn.close.assert_called_once()
        conn.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
