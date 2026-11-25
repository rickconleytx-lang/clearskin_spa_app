import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from jinja2 import DictLoader, Environment


WHEN = datetime(
    2026, 11, 18, 5, 0, tzinfo=timezone.utc
)


def revision(
    rid, number, wording,
    draft=False, published=False, was_published=False
):
    return {
        "revision_id": rid,
        "revision_number": number,
        "hero": {
            "primary_button_text": wording,
            "secondary_button_text": "View Pricing",
            "pricing_sentence": (
                "Solo is $49/month or $490/year "
                "after the 10-day free trial."
            ),
        },
        "created_by": 7,
        "created_at": WHEN,
        "change_note": None,
        "is_draft": draft,
        "is_published": published,
        "was_published": was_published,
    }


def sample_history():
    return {
        "draft_revision_id": 1,
        "published_revision_id": 1,
        "revisions": [
            revision(
                1, 1, "Start Your free trial today",
                draft=True,
                published=True,
                was_published=True,
            ),
        ],
        "events": [
            {
                "publication_event_id": 1,
                "revision_id": 1,
                "previous_revision_id": None,
                "action": "publish",
                "performed_by": 7,
                "performed_at": WHEN,
            },
        ],
    }


class FakeResponse:
    def __init__(self, body):
        self.body = body
        self.headers = {}


class MarketingCMSHistoryRouteTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(
            Path("app.py").read_text(encoding="utf-8")
        )

        matches = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "master_admin_website_home_history"
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

        cls.template_source = Path(
            "templates/master_admin_website_history.html"
        ).read_text(encoding="utf-8")

        cls.editor = Path(
            "templates/master_admin_website_management.html"
        ).read_text(encoding="utf-8")

    def invoke(self, history=None, error=None):
        conn = MagicMock()

        namespace = {
            "get_db_connection": lambda: conn,
            "render_template": (
                lambda name, **kwargs: (name, kwargs)
            ),
        }

        exec(self.code, namespace)

        with patch(
            "services.psp_marketing_cms_history."
            "load_home_history",
            return_value=(
                sample_history()
                if history is None
                else history
            ),
            side_effect=error,
        ) as loader, patch(
            "flask.make_response",
            side_effect=lambda body: FakeResponse(body),
        ):
            try:
                response = namespace[
                    "master_admin_website_home_history"
                ]()
                failure = None
            except Exception as exc:
                response = None
                failure = exc

            loader.assert_called_once_with(conn)

        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

        return response, failure

    def render_history(self, history=None):
        environment = Environment(
            loader=DictLoader({
                "base.html": (
                    "{% block content %}{% endblock %}"
                ),
                "history.html": self.template_source,
            }),
            autoescape=True,
        )

        return environment.get_template(
            "history.html"
        ).render(
            history=(
                sample_history()
                if history is None
                else history
            ),
            url_for=lambda endpoint: (
                "/master-admin/website"
            ),
        )

    def test_route_is_get_only_and_master_admin(self):
        self.assertIn("login_required", self.decorators)
        self.assertIn(
            "master_admin_required", self.decorators
        )
        self.assertTrue(any(
            "/master-admin/website/home/history" in item
            and "GET" in item
            for item in self.decorators
        ))

    def test_route_loads_history_without_writing(self):
        response, failure = self.invoke()

        self.assertIsNone(failure)

        name, values = response.body

        self.assertEqual(
            name,
            "master_admin_website_history.html",
        )
        self.assertEqual(
            values["history"]["published_revision_id"],
            1,
        )

    def test_history_error_closes_database_connection(self):
        response, failure = self.invoke(
            error=RuntimeError("Simulated history failure")
        )

        self.assertIsNone(response)
        self.assertIsInstance(failure, RuntimeError)

    def test_history_is_private_and_not_cached(self):
        response, failure = self.invoke()

        self.assertIsNone(failure)
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

    def test_current_published_and_draft_labels(self):
        html = self.render_history()

        self.assertIn(
            "Home Page Revision History", html
        )
        self.assertIn("Currently Published", html)
        self.assertIn("Current Draft", html)
        self.assertIn(
            "Start Your free trial today", html
        )

    def test_historical_revision_statuses(self):
        history = {
            "draft_revision_id": 3,
            "published_revision_id": 2,
            "revisions": [
                revision(3, 3, "Unpublished Draft",
                         draft=True),
                revision(2, 2, "Published Version",
                         published=True,
                         was_published=True),
                revision(1, 1, "Original Version",
                         was_published=True),
            ],
            "events": [],
        }

        html = self.render_history(history)

        self.assertIn("Never Published", html)
        self.assertIn("Previously Published", html)
        self.assertIn("Currently Published", html)
        self.assertIn("Unpublished Draft", html)
        self.assertIn("Original Version", html)

    def test_publication_events_are_displayed(self):
        history = sample_history()
        history["events"].insert(
            0,
            {
                "publication_event_id": 2,
                "revision_id": 1,
                "previous_revision_id": 2,
                "action": "restore",
                "performed_by": 7,
                "performed_at": WHEN,
            },
        )

        html = self.render_history(history)

        self.assertIn("Restore", html)
        self.assertIn("Publish", html)
        self.assertIn(
            "Publication Event ID:", html
        )
        self.assertIn(
            "Previous Published Revision:", html
        )

    def test_empty_history_renders_safely(self):
        html = self.render_history({
            "draft_revision_id": None,
            "published_revision_id": None,
            "revisions": [],
            "events": [],
        })

        self.assertIn(
            "No saved Home Page revisions yet.", html
        )
        self.assertIn(
            "No publication events have been recorded.",
            html,
        )

    def test_editor_has_unconditional_history_link(self):
        self.assertEqual(
            self.editor.count(
                "master_admin_website_home_history"
            ),
            1,
        )

        self.assertIn(
            "View Revision History", self.editor
        )

        self.assertLess(
            self.editor.index("{% endif %}"),
            self.editor.index("View Revision History"),
        )

    def test_historical_content_is_escaped(self):
        history = sample_history()

        history["revisions"][0]["hero"][
            "primary_button_text"
        ] = "<script>alert(1)</script>"

        html = self.render_history(history)

        self.assertNotIn(
            "<script>alert(1)</script>", html
        )
        self.assertIn(
            "&lt;script&gt;alert(1)&lt;/script&gt;",
            html,
        )
        self.assertNotIn("<form", html.lower())
        self.assertNotIn(
            'type="submit"', html.lower()
        )


if __name__ == "__main__":
    unittest.main()
