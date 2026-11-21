"""Tests for independent introduction draft dispatch.

These tests do not connect to a database.
"""

import copy
import unittest

from services.psp_marketing_cms_content import (
    MarketingContentError,
)

from services.psp_marketing_cms_sections import (
    MarketingCMSSectionError,
)

from services.psp_marketing_cms_service import (
    MarketingCMSConfigurationError,
    save_section_draft,
)


class NoDatabaseConnection:
    """Reject any attempt to execute SQL."""

    autocommit = True

    def cursor(self):
        raise AssertionError(
            "Database access is not allowed in this test."
        )


def example_intro():
    return {
        "intro": {
            "heading": "Launch Special",
            "paragraph": (
                "Peach Suite Pro subscriptions are available."
            ),
        }
    }


class IntroductionDraftServiceTests(unittest.TestCase):

    def save(self, section_key, content):
        return save_section_draft(
            NoDatabaseConnection(),
            section_key=section_key,
            content=content,
            actor_id=1,
            expected_draft_revision_id=None,
        )

    def test_packages_intro_dispatch(self):
        with self.assertRaises(
            MarketingCMSConfigurationError
        ):
            self.save(
                "packages.intro",
                example_intro(),
            )

    def test_pricing_intro_dispatch(self):
        with self.assertRaises(
            MarketingCMSConfigurationError
        ):
            self.save(
                "pricing.intro",
                example_intro(),
            )

    def test_packages_invalid_heading_rejected(self):
        content = example_intro()
        content["intro"]["heading"] = ""

        with self.assertRaises(MarketingContentError):
            self.save("packages.intro", content)

    def test_pricing_html_rejected(self):
        content = example_intro()
        content["intro"]["paragraph"] = "<script>bad</script>"

        with self.assertRaises(MarketingContentError):
            self.save("pricing.intro", content)

    def test_unknown_section_rejected(self):
        with self.assertRaises(MarketingCMSSectionError):
            self.save(
                "packages.unapproved",
                example_intro(),
            )

    def test_input_is_not_modified(self):
        content = example_intro()
        original = copy.deepcopy(content)

        with self.assertRaises(
            MarketingCMSConfigurationError
        ):
            self.save("packages.intro", content)

        self.assertEqual(content, original)


if __name__ == "__main__":
    unittest.main()
