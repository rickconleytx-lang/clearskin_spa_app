import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
)


class AbortedRequest(Exception):
    def __init__(self, status):
        self.status = status


class MarketingCMSSaveRouteTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = Path("app.py").read_text()
        tree = ast.parse(source)

        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "master_admin_website_save_draft"
        ]

        assert len(matches) == 1
        route = matches[0]

        decorator_source = [
            ast.unparse(d) for d in route.decorator_list
        ]
        assert "login_required" in decorator_source
        assert "master_admin_required" in decorator_source

        route.decorator_list = []
        cls.route_code = compile(
            ast.Module(body=[route], type_ignores=[]),
            "app.py",
            "exec",
        )

    @staticmethod
    def form(expected=""):
        return {
            "security_csrf_token": "test-token",
            "expected_draft_revision_id": expected,
            "primary_button_text": "Start Free Trial",
            "secondary_button_text": "View Pricing",
            "pricing_sentence": "Example website wording.",
        }

    def run_route(
        self,
        *,
        form=None,
        actor=1,
        valid_csrf=True,
        service_error=None,
    ):
        conn = MagicMock()
        connection_factory = MagicMock(return_value=conn)
        flashes = []

        namespace = {
            "request": SimpleNamespace(
                form=self.form() if form is None else form
            ),
            "session": {"user_id": actor},
            "_security_form_csrf_valid": (
                lambda value: valid_csrf
                and value == "test-token"
            ),
            "abort": lambda status: (
                (_ for _ in ()).throw(
                    AbortedRequest(status)
                )
            ),
            "get_db_connection": connection_factory,
            "flash": (
                lambda message, category:
                flashes.append((message, category))
            ),
            "url_for": lambda name: (
                "/master-admin/website"
            ),
            "redirect": lambda path: path,
        }

        exec(self.route_code, namespace)

        with patch(
            "services.psp_marketing_cms_service."
            "save_home_draft"
        ) as service:
            service.return_value = {
                "revision_number": 1,
                "revision_id": 42,
            }

            if service_error is not None:
                service.side_effect = service_error

            try:
                response = namespace[
                    "master_admin_website_save_draft"
                ]()
                failure = None
            except Exception as exc:
                response = None
                failure = exc

            return (
                response, failure, service,
                conn, connection_factory, flashes,
            )

    def test_first_draft_saves_privately(self):
        response, error, service, conn, factory, flashes = (
            self.run_route()
        )
        self.assertIsNone(error)
        self.assertEqual(response, "/master-admin/website")
        self.assertEqual(
            service.call_args.kwargs[
                "expected_draft_revision_id"
            ],
            None,
        )
        self.assertEqual(
            service.call_args.kwargs["actor_id"], 1
        )
        self.assertEqual(
            service.call_args.kwargs["content"]["hero"][
                "primary_button_text"
            ],
            "Start Free Trial",
        )
        self.assertEqual(factory.call_count, 1)
        conn.close.assert_called_once()
        self.assertIn(
            "public website has not changed",
            flashes[0][0],
        )

    def test_existing_draft_id_passed_to_service(self):
        result = self.run_route(form=self.form("42"))
        self.assertIsNone(result[1])
        self.assertEqual(
            result[2].call_args.kwargs[
                "expected_draft_revision_id"
            ],
            42,
        )

    def test_bad_csrf_rejected_before_database(self):
        result = self.run_route(valid_csrf=False)
        self.assertIsInstance(result[1], AbortedRequest)
        self.assertEqual(result[1].status, 400)
        result[4].assert_not_called()

    def test_bad_actor_rejected_before_database(self):
        result = self.run_route(actor=None)
        self.assertIsInstance(result[1], AbortedRequest)
        self.assertEqual(result[1].status, 403)
        result[4].assert_not_called()

    def test_invalid_expected_revision_rejected(self):
        for value in ("0", "-1", "abc", "1.5"):
            with self.subTest(value=value):
                result = self.run_route(
                    form=self.form(value)
                )
                self.assertIsInstance(
                    result[1], AbortedRequest
                )
                self.assertEqual(result[1].status, 400)
                result[4].assert_not_called()

    def test_stale_draft_does_not_report_success(self):
        result = self.run_route(
            service_error=MarketingCMSConflict("stale")
        )
        self.assertIsNone(result[1])
        self.assertEqual(result[0], "/master-admin/website")
        self.assertEqual(result[5][0][1], "error")
        result[3].close.assert_called_once()

    def test_invalid_content_reports_error(self):
        result = self.run_route(
            service_error=MarketingContentError(
                "Invalid content"
            )
        )
        self.assertIsNone(result[1])
        self.assertEqual(result[5][0][1], "error")
        result[3].close.assert_called_once()

    def test_unexpected_failure_closes_connection(self):
        result = self.run_route(
            service_error=RuntimeError("Database failure")
        )
        self.assertIsInstance(result[1], RuntimeError)
        result[3].close.assert_called_once()
        self.assertEqual(result[5], [])


if __name__ == "__main__":
    unittest.main()
