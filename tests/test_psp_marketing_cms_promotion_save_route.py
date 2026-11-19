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


class MarketingCMSPromotionSaveRouteTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = Path("app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == (
                "master_admin_website_promotion_save_draft"
            )
        ]

        assert len(matches) == 1

        route = matches[0]

        decorators = [
            ast.unparse(node)
            for node in route.decorator_list
        ]

        assert "login_required" in decorators
        assert "master_admin_required" in decorators
        assert any(
            "/master-admin/website/home/promotion/save" in value
            for value in decorators
        )

        cls.route_source = ast.get_source_segment(
            source, route
        )

        route.decorator_list = []

        cls.route_code = compile(
            ast.Module(body=[route], type_ignores=[]),
            "app.py",
            "exec",
        )

    @staticmethod
    def form(expected=""):
        fields = {
            "security_csrf_token": "test-token",
            "expected_draft_revision_id": expected,
            "product_label": "Solo",
            "headline": (
                "One business.\n"
                "One owner.\n"
                "One connected system."
            ),
            "monthly_price": "$49",
            "pricing_description": (
                "Or $490/year. Start with a 10-day free trial."
            ),
        }

        features = [
            "Client Management",
            "Appointment Calendar",
            "PeachBook",
            "PeachWeb",
            "Income & Expenses",
            "Inventory",
            "Coach Peach",
            "Square Integration",
            "Import & Export",
        ]

        for index, feature in enumerate(features, 1):
            fields[f"feature_{index}"] = feature

        return fields

    def run_route(
        self,
        *,
        form=None,
        actor=1,
        valid_csrf=True,
        service_error=None,
    ):
        conn = MagicMock()
        factory = MagicMock(return_value=conn)
        flashes = []

        namespace = {
            "request": SimpleNamespace(
                form=self.form() if form is None else form
            ),
            "session": {"user_id": actor},
            "_security_form_csrf_valid": (
                lambda token: valid_csrf
                and token == "test-token"
            ),
            "abort": lambda status: (
                (_ for _ in ()).throw(AbortedRequest(status))
            ),
            "get_db_connection": factory,
            "flash": lambda message, category: (
                flashes.append((message, category))
            ),
            "url_for": lambda endpoint: (
                "/master-admin/website"
            ),
            "redirect": lambda path: path,
        }

        exec(self.route_code, namespace)

        with patch(
            "services.psp_marketing_cms_service."
            "save_section_draft"
        ) as service:
            service.return_value = {
                "revision_number": 1,
                "revision_id": 501,
            }

            if service_error is not None:
                service.side_effect = service_error

            try:
                response = namespace[
                    "master_admin_website_promotion_save_draft"
                ]()
                error = None
            except Exception as exc:
                response = None
                error = exc

            return (
                response, error, service, conn,
                factory, flashes,
            )

    def test_saves_independent_promotion_with_line_breaks(self):
        result = self.run_route()

        self.assertIsNone(result[1])
        self.assertEqual(
            result[0], "/master-admin/website"
        )

        kwargs = result[2].call_args.kwargs

        self.assertEqual(kwargs["section_key"], "home.promo")
        self.assertEqual(kwargs["actor_id"], 1)
        self.assertIsNone(
            kwargs["expected_draft_revision_id"]
        )

        promotion = kwargs["content"]["promotion"]

        self.assertEqual(
            promotion["headline"].count("\n"), 2
        )
        self.assertEqual(
            len(promotion["features"]), 9
        )
        self.assertEqual(
            promotion["monthly_price"], "$49"
        )

        result[3].close.assert_called_once()

        self.assertIn(
            "public website has not changed",
            result[5][0][0],
        )

    def test_existing_revision_is_forwarded(self):
        result = self.run_route(form=self.form("501"))

        self.assertIsNone(result[1])
        self.assertEqual(
            result[2].call_args.kwargs[
                "expected_draft_revision_id"
            ],
            501,
        )

    def test_bad_csrf_rejected_before_database(self):
        result = self.run_route(valid_csrf=False)

        self.assertIsInstance(
            result[1], AbortedRequest
        )
        self.assertEqual(result[1].status, 400)
        result[4].assert_not_called()

    def test_invalid_actor_rejected_before_database(self):
        for actor in (None, 0, True, "invalid"):
            with self.subTest(actor=actor):
                result = self.run_route(actor=actor)

                self.assertIsInstance(
                    result[1], AbortedRequest
                )
                self.assertEqual(result[1].status, 403)
                result[4].assert_not_called()

    def test_invalid_revision_rejected_before_database(self):
        for value in ("0", "-1", "abc", "1.5", "9" * 20):
            with self.subTest(value=value):
                result = self.run_route(
                    form=self.form(value)
                )

                self.assertIsInstance(
                    result[1], AbortedRequest
                )
                self.assertEqual(result[1].status, 400)
                result[4].assert_not_called()

    def test_stale_draft_never_reports_success(self):
        result = self.run_route(
            service_error=MarketingCMSConflict("stale")
        )

        self.assertIsNone(result[1])
        self.assertEqual(result[5][0][1], "error")
        result[3].close.assert_called_once()

    def test_invalid_content_reports_error(self):
        result = self.run_route(
            service_error=MarketingContentError(
                "Invalid promotion"
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

    def test_route_has_no_publication_operation(self):
        self.assertNotIn(
            "publish_home_draft",
            self.route_source,
        )
        self.assertNotIn(
            "published_revision_id",
            self.route_source,
        )
        self.assertIn(
            'section_key="home.promo"',
            self.route_source,
        )


if __name__ == "__main__":
    unittest.main()
