import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jinja2 import DictLoader, Environment
from werkzeug.exceptions import NotFound, abort


WHEN = datetime(2026, 11, 18, tzinfo=timezone.utc)


def revision(rid, number, text, *, draft=False,
             published=False, was_published=False):
    return {
        "revision_id": rid,
        "revision_number": number,
        "hero": {
            "primary_button_text": text,
            "secondary_button_text": "View Pricing",
            "pricing_sentence": "Solo is $49/month.",
        },
        "created_at": WHEN,
        "created_by": 9,
        "change_note": None,
        "is_draft": draft,
        "is_published": published,
        "was_published": was_published,
    }


def sample_history():
    return {
        "draft_revision_id": 3,
        "published_revision_id": 2,
        "revisions": [
            revision(3, 3, "Private Draft", draft=True),
            revision(2, 2, "Current Public Text",
                     published=True, was_published=True),
            revision(1, 1, "Original Public Text",
                     was_published=True),
        ],
        "events": [],
    }


class FakeResponse:
    def __init__(self, body):
        self.body = body
        self.headers = {}


class MarketingCMSRestoreReviewTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(Path("app.py").read_text())

        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "master_admin_website_restore_review"
        ]
        assert len(matches) == 1

        route = matches[0]
        cls.decorators = [
            ast.unparse(item)
            for item in route.decorator_list
        ]
        route.decorator_list = []

        cls.code = compile(
            ast.fix_missing_locations(
                ast.Module(body=[route], type_ignores=[])
            ),
            "app.py",
            "exec",
        )

        cls.review = Path(
            "templates/master_admin_website_restore_review.html"
        ).read_text()

        cls.history_template = Path(
            "templates/master_admin_website_history.html"
        ).read_text()

    def invoke(self, revision_id="1", history=None, error=None):
        conn = MagicMock()
        factory = MagicMock(return_value=conn)

        args = (
            {} if revision_id is None
            else {"revision_id": revision_id}
        )

        namespace = {
            "request": SimpleNamespace(args=args),
            "get_db_connection": factory,
            "render_template": (
                lambda name, **kwargs: (name, kwargs)
            ),
            "abort": abort,
            "_security_form_csrf_token": lambda: "test-csrf-token",
        }

        exec(self.code, namespace)

        with patch(
            "services.psp_marketing_cms_history.load_home_history",
            return_value=(
                sample_history()
                if history is None else history
            ),
            side_effect=error,
        ) as loader, patch(
            "flask.make_response",
            side_effect=lambda body: FakeResponse(body),
        ):
            try:
                response = namespace[
                    "master_admin_website_restore_review"
                ]()
                failure = None
            except Exception as exc:
                response = None
                failure = exc

        return response, failure, conn, factory, loader

    def test_get_route_requires_master_admin(self):
        self.assertIn("login_required", self.decorators)
        self.assertIn("master_admin_required", self.decorators)
        self.assertTrue(any(
            "/master-admin/website/home/restore/review" in item
            and "GET" in item
            for item in self.decorators
        ))

    def test_valid_history_renders_both_versions(self):
        response, error, conn, factory, loader = self.invoke()
        self.assertIsNone(error)
        name, values = response.body
        self.assertEqual(
            name, "master_admin_website_restore_review.html"
        )
        self.assertEqual(values["target"]["revision_id"], 1)
        self.assertEqual(values["current"]["revision_id"], 2)
        self.assertEqual(values["draft_revision_id"], 3)
        factory.assert_called_once()
        loader.assert_called_once_with(conn)
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

    def test_invalid_id_rejected_before_database(self):
        for value in (
            None, "", "0", "-1", "abc", "2.5",
            "99999999999999999999",
        ):
            with self.subTest(value=value):
                _, error, _, factory, loader = self.invoke(
                    revision_id=value
                )
                self.assertIsInstance(error, NotFound)
                factory.assert_not_called()
                loader.assert_not_called()

    def test_active_published_revision_rejected(self):
        _, error, conn, _, _ = self.invoke("2")
        self.assertIsInstance(error, NotFound)
        conn.close.assert_called_once()

    def test_unpublished_draft_rejected(self):
        _, error, conn, _, _ = self.invoke("3")
        self.assertIsInstance(error, NotFound)
        conn.close.assert_called_once()

    def test_unknown_revision_rejected(self):
        _, error, _, _, _ = self.invoke("99")
        self.assertIsInstance(error, NotFound)

    def test_missing_current_publication_rejected(self):
        state = sample_history()
        state["published_revision_id"] = None
        _, error, _, _, _ = self.invoke(history=state)
        self.assertIsInstance(error, NotFound)

    def test_database_failure_closes_connection(self):
        _, error, conn, _, _ = self.invoke(
            error=RuntimeError("Simulated failure")
        )
        self.assertIsInstance(error, RuntimeError)
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_private_response_headers(self):
        response, error, _, _, _ = self.invoke()
        self.assertIsNone(error)
        self.assertIn(
            "no-store", response.headers["Cache-Control"]
        )
        self.assertIn(
            "noindex", response.headers["X-Robots-Tag"]
        )
        self.assertEqual(
            response.headers["Referrer-Policy"],
            "no-referrer",
        )

    def test_history_links_only_eligible_revisions(self):
        environment = Environment(
            loader=DictLoader({
                "base.html": (
                    "{% block content %}{% endblock %}"
                ),
                "history.html": self.history_template,
            }),
            autoescape=True,
        )

        rendered = environment.get_template(
            "history.html"
        ).render(
            history=sample_history(),
            url_for=lambda endpoint: "/restore/review",
        )

        self.assertEqual(
            rendered.count("Review Restoration"), 1
        )
        self.assertIn("revision_id=1", rendered)
        self.assertNotIn("revision_id=3", rendered)

    def _render_review(self, *, target_word=None):
        environment = Environment(
            loader=DictLoader({
                "base.html": (
                    "{% block content %}{% endblock %}"
                ),
                "review.html": self.review,
            }),
            autoescape=True,
        )

        data = sample_history()

        if target_word is not None:
            data["revisions"][2]["hero"][
                "primary_button_text"
            ] = target_word

        return environment.get_template(
            "review.html"
        ).render(
            target=data["revisions"][2],
            current=data["revisions"][1],
            draft_revision_id=3,
            security_csrf_token="test-csrf-token",
            url_for=lambda endpoint: (
                "/restore"
                if endpoint == (
                    "master_admin_website_restore_revision"
                )
                else "/history"
            ),
        )

    def test_review_requires_explicit_confirmation(self):
        html = self._render_review()

        self.assertIn("Original Public Text", html)
        self.assertIn("Current Public Text", html)
        self.assertIn("will be preserved", html)
        self.assertIn('<form method="POST"', html)
        self.assertIn('action="/restore"', html)
        self.assertIn('type="submit"', html)

    def test_get_route_supplies_csrf_token(self):
        response, error, conn, _, _ = self.invoke()

        self.assertIsNone(error)
        self.assertEqual(
            response.body[1]["security_csrf_token"],
            "test-csrf-token",
        )
        conn.commit.assert_not_called()

    def test_restore_form_sends_exact_revision_ids(self):
        import re

        html = self._render_review()

        self.assertRegex(
            html,
            r'name="revision_id"\s+value="1"',
        )
        self.assertRegex(
            html,
            r'name="expected_published_revision_id"'
            r'\s+value="2"',
        )
        self.assertRegex(
            html,
            r'name="security_csrf_token"'
            r'\s+value="test-csrf-token"',
        )

    def test_confirmation_must_be_typed(self):
        import re

        html = self._render_review()

        confirmation = re.search(
            r'<input\b[^>]*name="restore_confirmation"'
            r'[^>]*>',
            html,
            re.S,
        )

        self.assertIsNotNone(confirmation)
        field = confirmation.group(0)

        self.assertIn("required", field)
        self.assertIn('pattern="RESTORE"', field)
        self.assertIn('maxlength="7"', field)
        self.assertIn(
            "Type RESTORE to confirm", html
        )

    def test_cancel_is_preserved_and_content_escaped(self):
        html = self._render_review(
            target_word="<script>alert(1)</script>"
        )

        self.assertIn(
            "Return Without Restoring", html
        )
        self.assertIn('href="/history"', html)
        self.assertNotIn(
            "<script>alert(1)</script>", html
        )
        self.assertIn(
            "&lt;script&gt;alert(1)&lt;/script&gt;",
            html,
        )


if __name__ == "__main__":
    unittest.main()
