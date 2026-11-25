"""Website Management introduction navigation tests."""

import unittest
from pathlib import Path
from jinja2 import Environment


class IntroNavigationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = Path(
            "templates/master_admin_website_management.html"
        ).read_text()

    def test_template_compiles(self):
        Environment().parse(self.source)

    def test_packages_editor_link(self):
        self.assertIn(
            "surface='packages'",
            self.source,
        )

    def test_pricing_editor_link(self):
        self.assertIn(
            "surface='pricing'",
            self.source,
        )

    def test_correct_editor_endpoint(self):
        self.assertEqual(
            self.source.count(
                "master_admin_website_intro_editor"
            ),
            2,
        )

    def test_both_button_labels(self):
        self.assertIn(
            "Edit Subscription Packages Introduction",
            self.source,
        )
        self.assertIn(
            "Edit Pricing Introduction",
            self.source,
        )

    def test_old_placeholder_removed(self):
        self.assertNotIn(
            "after the Home Page editor is verified",
            self.source,
        )

    def test_existing_showcase_links_preserved(self):
        self.assertIn(
            "master_admin_website_peachweb_editor",
            self.source,
        )
        self.assertIn(
            "master_admin_website_peachbook_editor",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
