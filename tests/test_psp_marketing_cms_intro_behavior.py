"""Isolated behavioral tests for Packages/Pricing intro routes.

The real route bodies run with mocked dependencies.
Existing structural tests separately check authorization decorators.
"""

import ast
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
)


class RouteAbort(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(str(status))


def abort(status):
    raise RouteAbort(status)


def intro(heading, paragraph):
    return {
        "intro": {
            "heading": heading,
            "paragraph": paragraph,
        }
    }


def section_state(draft=None, published=None, revision=None):
    return {
        "draft_revision_id": revision,
        "draft_content": draft,
        "published_revision_id": None,
        "published_content": published,
    }


def extract_routes():
    tree = ast.parse(Path("app.py").read_text())

    names = (
        "master_admin_website_intro_editor",
        "master_admin_website_intro_save_draft",
    )

    selected = []

    for name in names:
        matches = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == name
        ]

        if len(matches) != 1:
            raise AssertionError(
                "Expected exactly one route: " + name
            )

        function = copy.deepcopy(matches[0])

        # Flask decorators are verified in separate structural tests.
        function.decorator_list = []
        selected.append(function)

    module = ast.fix_missing_locations(
        ast.Module(body=selected, type_ignores=[])
    )

    return compile(
        module,
        "app.py [isolated introduction routes]",
        "exec",
    )


ROUTES = extract_routes()


class IntroductionBehaviorTests(unittest.TestCase):

    def setUp(self):
        self.conn = Mock(name="database_connection")

        self.context = {
            "get_db_connection": Mock(
                return_value=self.conn
            ),
            "abort": abort,
            "request": SimpleNamespace(form={}),
            "session": {"user_id": 17},
            "render_template": Mock(
                side_effect=lambda name, **kwargs: {
                    "template": name,
                    **kwargs,
                }
            ),
            "url_for": Mock(
                side_effect=lambda endpoint, surface: (
                    f"/master-admin/website/{surface}/intro"
                )
            ),
            "redirect": Mock(
                side_effect=lambda location: {
                    "redirect_to": location
                }
            ),
            "flash": Mock(),
            "_security_form_csrf_token": Mock(
                return_value="csrf-test"
            ),
            "_security_form_csrf_valid": Mock(
                return_value=True
            ),
        }

        exec(ROUTES, self.context)

        self.get = self.context[
            "master_admin_website_intro_editor"
        ]

        self.save = self.context[
            "master_admin_website_intro_save_draft"
        ]

        read_patch = patch(
            "services.psp_marketing_cms_service."
            "load_section_state"
        )
        save_patch = patch(
            "services.psp_marketing_cms_service."
            "save_section_draft"
        )

        self.load = read_patch.start()
        self.persist = save_patch.start()

        self.addCleanup(read_patch.stop)
        self.addCleanup(save_patch.stop)

        self.load.return_value = section_state()
        self.persist.return_value = {
            "revision_number": 1
        }

    def form(self, **overrides):
        values = {
            "security_csrf_token": "csrf-test",
            "expected_draft_revision_id": "",
            "heading": "New heading",
            "paragraph": "First line\nSecond line",
        }

        values.update(overrides)
        self.context["request"].form = values

    def test_get_packages_initial_content(self):
        result = self.get("packages")

        self.assertEqual(
            result["surface"], "packages"
        )
        self.assertEqual(
            result["page_label"],
            "Subscription Packages",
        )
        self.assertEqual(
            result["content_source"],
            "existing website wording",
        )
        self.assertIn(
            "LAUNCH10",
            result["intro"]["paragraph"],
        )

        self.load.assert_called_once_with(
            self.conn,
            section_key="packages.intro",
        )
        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_get_pricing_initial_content(self):
        result = self.get("pricing")

        self.assertEqual(
            result["page_label"], "Pricing"
        )
        self.assertIn(
            "LAUNCH10",
            result["intro"]["paragraph"],
        )

        self.load.assert_called_once_with(
            self.conn,
            section_key="pricing.intro",
        )

    def test_get_saved_draft_precedence(self):
        self.load.return_value = section_state(
            draft=intro(
                "Draft heading",
                "Draft paragraph",
            ),
            published=intro(
                "Published heading",
                "Published paragraph",
            ),
            revision=22,
        )

        result = self.get("packages")

        self.assertEqual(
            result["intro"]["heading"],
            "Draft heading",
        )
        self.assertEqual(
            result["content_source"],
            "saved draft",
        )
        self.assertEqual(
            result["draft_revision_id"], 22
        )

    def test_get_uses_published_when_no_draft(self):
        self.load.return_value = section_state(
            published=intro(
                "Pricing publication",
                "Pricing text",
            )
        )

        result = self.get("pricing")

        self.assertEqual(
            result["intro"]["heading"],
            "Pricing publication",
        )
        self.assertEqual(
            result["content_source"],
            "published content",
        )

    def test_get_independent_page_content(self):
        def read_state(conn, *, section_key):
            if section_key == "packages.intro":
                return section_state(
                    draft=intro(
                        "Packages only", "Packages text"
                    ),
                    revision=4,
                )

            return section_state(
                draft=intro(
                    "Pricing only", "Pricing text"
                ),
                revision=8,
            )

        self.load.side_effect = read_state

        packages = self.get("packages")
        pricing = self.get("pricing")

        self.assertEqual(
            packages["intro"]["heading"],
            "Packages only",
        )
        self.assertEqual(
            pricing["intro"]["heading"],
            "Pricing only",
        )
        self.assertEqual(
            packages["draft_revision_id"], 4
        )
        self.assertEqual(
            pricing["draft_revision_id"], 8
        )

    def test_get_unknown_surface_rejected(self):
        with self.assertRaises(RouteAbort) as error:
            self.get("unknown")

        self.assertEqual(error.exception.status, 404)

        self.context[
            "get_db_connection"
        ].assert_not_called()

    def test_get_database_error_closes_connection(self):
        self.load.side_effect = RuntimeError(
            "Simulated read failure"
        )

        with self.assertRaises(RuntimeError):
            self.get("packages")

        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_get_invalid_stored_content_rejected(self):
        self.load.return_value = section_state(
            draft=intro(
                "<script>bad</script>",
                "Text",
            ),
            revision=1,
        )

        with self.assertRaises(MarketingContentError):
            self.get("packages")

        self.conn.close.assert_called_once()

    def test_save_first_packages_draft(self):
        self.form()

        result = self.save("packages")

        self.assertEqual(
            result["redirect_to"],
            "/master-admin/website/packages/intro",
        )

        self.persist.assert_called_once_with(
            self.conn,
            section_key="packages.intro",
            content=intro(
                "New heading",
                "First line\nSecond line",
            ),
            actor_id=17,
            expected_draft_revision_id=None,
        )

        self.conn.close.assert_called_once()

        self.assertIn(
            "public website has not changed",
            str(self.context["flash"].call_args),
        )

    def test_save_pricing_revision_precondition(self):
        self.form(
            expected_draft_revision_id="42"
        )

        self.save("pricing")

        self.assertEqual(
            self.persist.call_args.kwargs[
                "section_key"
            ],
            "pricing.intro",
        )
        self.assertEqual(
            self.persist.call_args.kwargs[
                "expected_draft_revision_id"
            ],
            42,
        )

    def test_save_rejects_invalid_csrf(self):
        self.form()

        self.context[
            "_security_form_csrf_valid"
        ].return_value = False

        with self.assertRaises(RouteAbort) as error:
            self.save("packages")

        self.assertEqual(error.exception.status, 400)

        self.context[
            "get_db_connection"
        ].assert_not_called()

    def test_save_rejects_invalid_actor(self):
        self.form()
        self.context["session"]["user_id"] = None

        with self.assertRaises(RouteAbort) as error:
            self.save("packages")

        self.assertEqual(error.exception.status, 403)

        self.context[
            "get_db_connection"
        ].assert_not_called()

    def test_save_rejects_invalid_revision(self):
        self.form(
            expected_draft_revision_id="not-an-id"
        )

        with self.assertRaises(RouteAbort) as error:
            self.save("pricing")

        self.assertEqual(error.exception.status, 400)

        self.context[
            "get_db_connection"
        ].assert_not_called()

    def test_save_unknown_surface_rejected(self):
        self.form()

        with self.assertRaises(RouteAbort) as error:
            self.save("unknown")

        self.assertEqual(error.exception.status, 404)

        self.context[
            "get_db_connection"
        ].assert_not_called()

    def test_save_stale_revision_conflict(self):
        self.form(
            expected_draft_revision_id="11"
        )

        self.persist.side_effect = MarketingCMSConflict(
            "Stale revision"
        )

        result = self.save("packages")

        self.assertEqual(
            result["redirect_to"],
            "/master-admin/website/packages/intro",
        )

        self.assertIn(
            "newer introduction draft",
            str(self.context["flash"].call_args),
        )

        self.conn.close.assert_called_once()

    def test_save_invalid_content(self):
        self.form()

        self.persist.side_effect = MarketingContentError(
            "Invalid heading"
        )

        result = self.save("pricing")

        self.assertEqual(
            result["redirect_to"],
            "/master-admin/website/pricing/intro",
        )

        self.assertIn(
            "Invalid heading",
            str(self.context["flash"].call_args),
        )

        self.conn.close.assert_called_once()

    def test_save_database_failure_closes_connection(self):
        self.form()

        self.persist.side_effect = RuntimeError(
            "Simulated database failure"
        )

        with self.assertRaises(RuntimeError):
            self.save("packages")

        self.conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
