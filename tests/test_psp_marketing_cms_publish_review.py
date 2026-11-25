import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from jinja2 import Environment
from werkzeug.exceptions import InternalServerError, abort

from services.psp_marketing_cms_content import (
    MarketingContentError,
)


def sample_content(primary="Start Your free trial today"):
    return {
        "hero": {
            "primary_button_text": primary,
            "secondary_button_text": "View Pricing",
            "pricing_sentence": (
                "Solo is $49/month or $490/year "
                "after the 10-day free trial."
            ),
        },
    }


class FakeResponse:
    def __init__(self, body):
        self.body = body
        self.headers = {}


class MarketingCMSPublishReviewTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(
            Path("app.py").read_text(encoding="utf-8")
        )

        matches = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "master_admin_website_publish_review"
        ]

        assert len(matches) == 1
        route = matches[0]

        cls.decorators = [
            ast.unparse(item)
            for item in route.decorator_list
        ]

        route.decorator_list = []

        cls.route_code = compile(
            ast.fix_missing_locations(
                ast.Module(body=[route], type_ignores=[])
            ),
            "app.py",
            "exec",
        )

        cls.review = Path(
            "templates/master_admin_website_publish_review.html"
        ).read_text(encoding="utf-8")

        cls.editor = Path(
            "templates/master_admin_website_management.html"
        ).read_text(encoding="utf-8")

    def invoke(self, state=None, error=None):
        conn = MagicMock()
        flashes = []

        namespace = {
            "_security_form_csrf_token": (
                lambda: "review-test-token"
            ),
            "get_db_connection": lambda: conn,
            "render_template": (
                lambda name, **kwargs: (name, kwargs)
            ),
            "url_for": (
                lambda endpoint: "/master-admin/website"
            ),
            "redirect": lambda path: ("redirect", path),
            "flash": (
                lambda message, category:
                flashes.append((message, category))
            ),
            "abort": abort,
        }

        exec(self.route_code, namespace)

        with patch(
            "services.psp_marketing_cms_service.load_home_state",
            return_value=state,
            side_effect=error,
        ) as loader, patch(
            "flask.make_response",
            side_effect=lambda value: FakeResponse(value),
        ):
            try:
                response = namespace[
                    "master_admin_website_publish_review"
                ]()
                failure = None
            except Exception as exc:
                response = None
                failure = exc

            loader.assert_called_once_with(conn)

        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

        return response, failure, flashes

    def test_get_route_requires_master_admin(self):
        self.assertIn("login_required", self.decorators)
        self.assertIn(
            "master_admin_required", self.decorators
        )
        self.assertTrue(any(
            "/master-admin/website/home/review" in item
            and "GET" in item
            for item in self.decorators
        ))

    def test_first_publication_review(self):
        response, error, _ = self.invoke({
            "draft_revision_id": 42,
            "draft_content": sample_content(),
            "published_revision_id": None,
            "published_content": None,
        })

        self.assertIsNone(error)
        name, values = response.body

        self.assertEqual(
            name,
            "master_admin_website_publish_review.html",
        )
        self.assertEqual(values["draft_revision_id"], 42)
        self.assertIsNone(values["published_revision_id"])
        self.assertIsNone(values["published_hero"])
        self.assertEqual(
            values["draft_hero"]["primary_button_text"],
            "Start Your free trial today",
        )

    def test_existing_publication_shown_separately(self):
        response, error, _ = self.invoke({
            "draft_revision_id": 42,
            "draft_content": sample_content("New Draft"),
            "published_revision_id": 31,
            "published_content": sample_content(
                "Currently Published"
            ),
        })

        self.assertIsNone(error)
        _, values = response.body

        self.assertEqual(values["published_revision_id"], 31)
        self.assertEqual(
            values["draft_hero"]["primary_button_text"],
            "New Draft",
        )
        self.assertEqual(
            values["published_hero"]["primary_button_text"],
            "Currently Published",
        )

    def test_missing_draft_redirects_without_publish(self):
        response, error, flashes = self.invoke({
            "draft_revision_id": None,
            "draft_content": None,
            "published_revision_id": None,
            "published_content": None,
        })

        self.assertIsNone(error)
        self.assertEqual(
            response,
            ("redirect", "/master-admin/website"),
        )
        self.assertEqual(flashes[0][1], "error")

    def test_invalid_draft_is_rejected(self):
        _, error, _ = self.invoke({
            "draft_revision_id": 42,
            "draft_content": {"hero": {}},
            "published_revision_id": None,
            "published_content": None,
        })

        self.assertIsInstance(error, MarketingContentError)

    def test_invalid_published_content_is_rejected(self):
        _, error, _ = self.invoke({
            "draft_revision_id": 42,
            "draft_content": sample_content(),
            "published_revision_id": 31,
            "published_content": {"hero": {}},
        })

        self.assertIsInstance(error, MarketingContentError)

    def test_mismatched_publication_state_is_rejected(self):
        _, error, _ = self.invoke({
            "draft_revision_id": 42,
            "draft_content": sample_content(),
            "published_revision_id": 31,
            "published_content": None,
        })

        self.assertIsInstance(error, InternalServerError)

    def test_database_error_closes_connection(self):
        _, error, _ = self.invoke(
            error=RuntimeError("Simulated database failure")
        )

        self.assertIsInstance(error, RuntimeError)

    def test_review_is_private_and_not_cached(self):
        response, error, _ = self.invoke({
            "draft_revision_id": 42,
            "draft_content": sample_content(),
            "published_revision_id": None,
            "published_content": None,
        })

        self.assertIsNone(error)
        self.assertIn(
            "no-store",
            response.headers["Cache-Control"],
        )
        self.assertIn(
            "noindex",
            response.headers["X-Robots-Tag"],
        )
        self.assertEqual(
            response.headers["Referrer-Policy"],
            "no-referrer",
        )

    def test_review_template_has_controlled_publish_form(self):
        Environment().parse(self.review)
        Environment().parse(self.editor)

        self.assertEqual(self.review.count("<form"), 1)
        self.assertEqual(self.review.count("</form>"), 1)
        self.assertIn('method="POST"', self.review)
        self.assertIn(
            "master_admin_website_publish_draft",
            self.review,
        )
        self.assertIn(
            "Return Without Publishing",
            self.review,
        )
        self.assertIn(
            "Review for Publishing",
            self.editor,
        )




    def render_publish_controls(
        self, draft_id=42, published_id=None
    ):
        marker = (
            "{% if draft_revision_id != published_revision_id %}"
        )

        self.assertEqual(self.review.count(marker), 1)

        start = self.review.index(marker)
        end = self.review.index(
            "{% endif %}", start
        ) + len("{% endif %}")

        template = Environment(
            autoescape=True
        ).from_string(self.review[start:end])

        return template.render(
            draft_revision_id=draft_id,
            published_revision_id=published_id,
            security_csrf_token="review-test-token",
            url_for=lambda endpoint: (
                "/master-admin/website/home/publish"
            ),
        )

    def test_review_supplies_csrf_token(self):
        response, error, _ = self.invoke({
            "draft_revision_id": 42,
            "draft_content": sample_content(),
            "published_revision_id": None,
            "published_content": None,
        })

        self.assertIsNone(error)

        _, values = response.body

        self.assertEqual(
            values["security_csrf_token"],
            "review-test-token",
        )

    def test_first_publish_form_contains_revision_ids(self):
        html = self.render_publish_controls()

        self.assertIn(
            'action="/master-admin/website/home/publish"',
            html,
        )
        self.assertIn(
            'name="security_csrf_token"',
            html,
        )
        self.assertIn(
            'value="review-test-token"',
            html,
        )
        self.assertIn(
            'name="expected_draft_revision_id"',
            html,
        )
        self.assertIn(
            'name="expected_published_revision_id"',
            html,
        )
        self.assertIn('value="42"', html)
        self.assertIn('value=""', html)

    def test_existing_published_id_is_in_confirmation(self):
        import re

        html = self.render_publish_controls(
            draft_id=42,
            published_id=31,
        )

        self.assertRegex(
            html,
            re.compile(
                r'name="expected_published_revision_id"'
                r'\s+value="31"'
            ),
        )

    def test_same_revision_cannot_be_resubmitted(self):
        html = self.render_publish_controls(
            draft_id=42,
            published_id=42,
        )

        self.assertNotIn("<form", html)
        self.assertNotIn(
            "Publish This Revision",
            html,
        )
        self.assertIn(
            "already published",
            html,
        )

    def test_publish_confirmation_requires_exact_keyword(self):
        html = self.render_publish_controls()

        self.assertIn(
            'name="publish_confirmation"',
            html,
        )
        self.assertIn('pattern="PUBLISH"', html)
        self.assertIn('maxlength="7"', html)
        self.assertIn("required", html)
        self.assertNotIn('value="PUBLISH"', html)
        self.assertIn(
            "Return Without Publishing",
            self.review,
        )

    def test_review_intro_describes_confirmation(self):
        self.assertIn(
            "Publishing occurs only",
            self.review,
        )
        self.assertIn(
            "submit the confirmation form",
            self.review,
        )
        self.assertNotIn(
            "This screen does not publish content.",
            self.review,
        )


if __name__ == "__main__":
    unittest.main()
