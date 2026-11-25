"""Isolated public introduction route tests.

No database connections or public HTTP requests are made.
"""

import ast
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


SOURCE = Path("app.py").read_text()
TREE = ast.parse(SOURCE)


def extract_function(name):
    matches = [
        node for node in TREE.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]
    if len(matches) != 1:
        raise AssertionError("Expected exactly one " + name)
    return matches[0]


HELPER = extract_function("_load_public_marketing_intro")
PUBLIC_ROUTE = extract_function("route_public_marketing_site")

helper_node = copy.deepcopy(HELPER)
helper_node.decorator_list = []

module = ast.fix_missing_locations(
    ast.Module(body=[helper_node], type_ignores=[])
)
HELPER_CODE = compile(
    module, "app.py [isolated public intro]", "exec"
)


class PublicIntroductionRouteTests(unittest.TestCase):

    def setUp(self):
        self.conn = Mock()
        self.db = Mock(return_value=self.conn)
        self.logger = Mock()
        self.app = SimpleNamespace(logger=self.logger)

        reader_patch = patch(
            "services.psp_marketing_cms_public_intro."
            "load_published_intro"
        )
        self.reader = reader_patch.start()
        self.addCleanup(reader_patch.stop)

        self.reader.return_value = {
            "heading": "Published Heading",
            "paragraph": "Use LAUNCH10.",
        }

        namespace = {
            "get_db_connection": self.db,
            "app": self.app,
        }

        exec(HELPER_CODE, namespace)
        self.helper = namespace["_load_public_marketing_intro"]

    def test_packages_published_content(self):
        result = self.helper("packages.intro")
        self.assertEqual(result["heading"], "Published Heading")
        self.reader.assert_called_once_with(
            self.conn, section_key="packages.intro"
        )

    def test_pricing_is_independent(self):
        self.helper("pricing.intro")
        self.reader.assert_called_once_with(
            self.conn, section_key="pricing.intro"
        )

    def test_no_publication_returns_none(self):
        self.reader.return_value = None
        self.assertIsNone(self.helper("pricing.intro"))

    def test_connection_failure_falls_back(self):
        self.db.side_effect = RuntimeError("DB unavailable")
        self.assertIsNone(self.helper("packages.intro"))

    def test_reader_failure_falls_back(self):
        self.reader.side_effect = ValueError("Invalid content")
        self.assertIsNone(self.helper("packages.intro"))

    def test_rollback_failure_falls_back(self):
        self.conn.rollback.side_effect = RuntimeError(
            "Rollback failed"
        )
        self.assertIsNone(self.helper("packages.intro"))
        self.conn.close.assert_called_once()

    def test_close_failure_falls_back(self):
        self.conn.close.side_effect = RuntimeError(
            "Close failed"
        )
        self.assertIsNone(self.helper("pricing.intro"))

    def test_both_cleanup_failures_fall_back(self):
        self.conn.rollback.side_effect = RuntimeError(
            "Rollback failed"
        )
        self.conn.close.side_effect = RuntimeError(
            "Close failed"
        )
        self.assertIsNone(self.helper("packages.intro"))

    def test_reader_error_still_cleans_up(self):
        self.reader.side_effect = RuntimeError(
            "Read failed"
        )
        self.helper("packages.intro")
        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_connection_error_has_no_connection_cleanup(self):
        self.db.side_effect = RuntimeError(
            "Connection failed"
        )
        self.helper("packages.intro")
        self.conn.rollback.assert_not_called()
        self.conn.close.assert_not_called()

    def test_no_database_commits(self):
        self.helper("packages.intro")
        self.conn.commit.assert_not_called()
        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()

    def test_success_does_not_log_exception(self):
        self.helper("packages.intro")
        self.logger.exception.assert_not_called()

    def test_failure_logs_and_falls_back(self):
        self.reader.side_effect = RuntimeError(
            "Invalid published content"
        )
        self.assertIsNone(self.helper("pricing.intro"))
        self.logger.exception.assert_called_once()

    def test_packages_route_passes_cms_context(self):
        route = ast.get_source_segment(SOURCE, PUBLIC_ROUTE)
        self.assertIn(
            '"public_site/psp_packages.html",',
            route,
        )
        self.assertIn(
            'cms_intro=_load_public_marketing_intro('
            '\n                "packages.intro"',
            route,
        )

    def test_pricing_route_passes_cms_context(self):
        route = ast.get_source_segment(SOURCE, PUBLIC_ROUTE)
        self.assertIn(
            '"public_site/psp_pricing.html",',
            route,
        )
        self.assertIn(
            'cms_intro=_load_public_marketing_intro('
            '\n                "pricing.intro"',
            route,
        )

    def test_existing_public_routes_remain(self):
        route = ast.get_source_segment(SOURCE, PUBLIC_ROUTE)
        for required in (
            'load_home_state',
            'public_site/psp_home.html',
            'public_site/psp_privacy_policy.html',
            'public_site/psp_terms',
            '"/subscription-packages/"',
            '"/pricing/"',
        ):
            self.assertIn(required, route)


if __name__ == "__main__":
    unittest.main()
