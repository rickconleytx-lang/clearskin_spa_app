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

from services.psp_marketing_cms_publication import (
    MarketingCMSUnpublishedRevision,
)
from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
)


class MarketingCMSRestoreRouteTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(
            Path("app.py").read_text(encoding="utf-8")
        )

        functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == (
                "master_admin_website_restore_revision"
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

        cls.history_template = Path(
            "templates/master_admin_website_history.html"
        ).read_text(encoding="utf-8")

    def invoke(
        self,
        *,
        changes=None,
        missing=(),
        actor="9",
        service_error=None,
    ):
        form = {
            "security_csrf_token": "valid-token",
            "restore_confirmation": "RESTORE",
            "revision_id": "1",
            "expected_published_revision_id": "2",
        }

        if changes:
            form.update(changes)

        for field in missing:
            form.pop(field, None)

        conn = MagicMock()
        factory = MagicMock(return_value=conn)
        notices = []

        namespace = {
            "request": SimpleNamespace(form=form),
            "session": {"user_id": actor},
            "_security_form_csrf_valid": (
                lambda token: token == "valid-token"
            ),
            "get_db_connection": factory,
            "flash": (
                lambda message, category:
                notices.append((message, category))
            ),
            "redirect": (
                lambda location: ("redirect", location)
            ),
            "url_for": (
                lambda endpoint:
                "/master-admin/website/home/history"
            ),
            "abort": abort,
        }

        exec(self.code, namespace)

        with patch(
            "services.psp_marketing_cms_publication."
            "restore_home_revision",
            return_value={
                "revision_id": 1,
                "previous_revision_id": 2,
                "publication_event_id": 3,
                "action": "restore",
            },
            side_effect=service_error,
        ) as restorer:
            try:
                response = namespace[
                    "master_admin_website_restore_revision"
                ]()
                failure = None
            except Exception as exc:
                response = None
                failure = exc

            calls = list(restorer.call_args_list)

        return (
            response,
            failure,
            calls,
            conn,
            factory,
            notices,
        )

    def test_route_is_post_only_and_master_admin(self):
        self.assertIn(
            "login_required", self.decorators
        )
        self.assertIn(
            "master_admin_required", self.decorators
        )

        self.assertTrue(any(
            "/master-admin/website/home/restore" in item
            and "POST" in item
            for item in self.decorators
        ))

        self.assertNotIn(
            "master_admin_website_restore_revision",
            self.history_template,
        )

    def test_restore_passes_target_and_current_publication(self):
        response, error, calls, conn, _, notices = (
            self.invoke()
        )

        self.assertIsNone(error)
        self.assertEqual(len(calls), 1)

        args, kwargs = calls[0]

        self.assertEqual(args, (conn,))
        self.assertEqual(kwargs, {
            "actor_id": 9,
            "revision_id": 1,
            "expected_published_revision_id": 2,
        })

        self.assertEqual(
            response,
            (
                "redirect",
                "/master-admin/website/home/history",
            ),
        )

        self.assertEqual(notices[0][1], "success")
        self.assertIn(
            "current draft has been preserved",
            notices[0][0],
        )

        conn.close.assert_called_once()
        conn.commit.assert_not_called()

    def test_bad_csrf_rejected_before_db(self):
        _, error, calls, _, factory, _ = self.invoke(
            changes={
                "security_csrf_token": "invalid",
            }
        )

        self.assertIsInstance(error, BadRequest)
        self.assertEqual(calls, [])
        factory.assert_not_called()

    def test_confirmation_requires_restore(self):
        for value in ("", "PUBLISH", "restore", "NO"):
            with self.subTest(value=value):
                _, error, calls, _, factory, _ = (
                    self.invoke(
                        changes={
                            "restore_confirmation": value,
                        }
                    )
                )

                self.assertIsInstance(
                    error, BadRequest
                )
                self.assertEqual(calls, [])
                factory.assert_not_called()

    def test_missing_actor_rejected(self):
        _, error, calls, _, factory, _ = self.invoke(
            actor=None
        )

        self.assertIsInstance(error, Forbidden)
        self.assertEqual(calls, [])
        factory.assert_not_called()

    def test_invalid_target_rejected(self):
        for value in (
            "", "0", "-1", "abc", "1.5",
            "99999999999999999999",
        ):
            with self.subTest(value=value):
                _, error, calls, _, factory, _ = (
                    self.invoke(
                        changes={"revision_id": value}
                    )
                )

                self.assertIsInstance(
                    error, BadRequest
                )
                self.assertEqual(calls, [])
                factory.assert_not_called()

    def test_missing_target_rejected(self):
        _, error, calls, _, factory, _ = self.invoke(
            missing=("revision_id",)
        )

        self.assertIsInstance(error, BadRequest)
        self.assertEqual(calls, [])
        factory.assert_not_called()

    def test_invalid_published_revision_rejected(self):
        for value in ("", "0", "-1", "abc"):
            with self.subTest(value=value):
                _, error, calls, _, factory, _ = (
                    self.invoke(
                        changes={
                            "expected_published_revision_id": value
                        }
                    )
                )

                self.assertIsInstance(
                    error, BadRequest
                )
                self.assertEqual(calls, [])
                factory.assert_not_called()

    def test_missing_published_revision_rejected(self):
        _, error, calls, _, factory, _ = self.invoke(
            missing=("expected_published_revision_id",)
        )

        self.assertIsInstance(error, BadRequest)
        self.assertEqual(calls, [])
        factory.assert_not_called()

    def test_same_revision_rejected(self):
        _, error, calls, _, factory, _ = self.invoke(
            changes={
                "revision_id": "2",
                "expected_published_revision_id": "2",
            }
        )

        self.assertIsInstance(error, BadRequest)
        self.assertEqual(calls, [])
        factory.assert_not_called()

    def test_stale_published_revision_reports_conflict(self):
        response, error, calls, conn, _, notices = (
            self.invoke(
                service_error=MarketingCMSConflict(
                    "Simulated stale publication"
                )
            )
        )

        self.assertIsNone(error)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            response,
            (
                "redirect",
                "/master-admin/website/home/history",
            ),
        )
        self.assertEqual(notices[0][1], "error")
        self.assertIn(
            "changed", notices[0][0]
        )
        conn.close.assert_called_once()

    def test_never_published_target_reports_error(self):
        response, error, calls, conn, _, notices = (
            self.invoke(
                service_error=MarketingCMSUnpublishedRevision(
                    "Simulated unpublished target"
                )
            )
        )

        self.assertIsNone(error)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            response,
            (
                "redirect",
                "/master-admin/website/home/history",
            ),
        )
        self.assertEqual(notices[0][1], "error")
        self.assertIn(
            "never been published",
            notices[0][0],
        )
        conn.close.assert_called_once()

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
