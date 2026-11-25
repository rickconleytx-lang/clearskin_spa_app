"""Tests for independent page introduction registration."""

import unittest
from pathlib import Path

from services.psp_marketing_cms_sections import (
    get_section_spec,
    sections_for_surface,
)


class IntroductionSectionTests(unittest.TestCase):

    def test_packages_registration(self):
        section = get_section_spec("packages.intro")
        self.assertEqual(section.kind, "intro")
        self.assertEqual(section.surfaces, ("packages",))

    def test_pricing_registration(self):
        section = get_section_spec("pricing.intro")
        self.assertEqual(section.kind, "intro")
        self.assertEqual(section.surfaces, ("pricing",))

    def test_packages_surface_contains_own_intro(self):
        keys = {
            section.key
            for section in sections_for_surface("packages")
        }
        self.assertIn("packages.intro", keys)
        self.assertNotIn("pricing.intro", keys)

    def test_pricing_surface_contains_own_intro(self):
        keys = {
            section.key
            for section in sections_for_surface("pricing")
        }
        self.assertIn("pricing.intro", keys)
        self.assertNotIn("packages.intro", keys)

    def test_migration_is_additive(self):
        path = Path(
            "migrations/psp_marketing_cms_page_intros_v3.sql"
        )
        sql = path.read_text()

        self.assertIn("'packages.intro'", sql)
        self.assertIn("'pricing.intro'", sql)

        self.assertEqual(
            sql.count("ON CONFLICT (page_key) DO NOTHING"),
            2,
        )

        self.assertIn(
            "INSERT INTO psp_marketing_pages",
            sql,
        )

        self.assertIn(
            "INSERT INTO psp_marketing_page_state",
            sql,
        )

        for forbidden in (
            "ALTER TABLE",
            "DROP TABLE",
            "DELETE FROM",
            "UPDATE psp_marketing",
        ):
            self.assertNotIn(forbidden, sql)


if __name__ == "__main__":
    unittest.main()
