"""Shared product CMS draft-saving tests.

Uses mock database transactions; no PostgreSQL connection.
"""

import copy
import unittest
from unittest.mock import MagicMock

from services.psp_marketing_cms_content import MarketingContentError
from services.psp_marketing_cms_sections import MarketingCMSSectionError
from services.psp_marketing_cms_service import (
    MarketingCMSConfigurationError,
    MarketingCMSConflict,
    save_section_draft,
)


def valid_product():
    return {
        "shared": {
            "status": "available",
            "bubble_text": "Available Now",
            "name": "Solo",
            "monthly_price": "$49",
            "annual_price": "$490",
            "monthly_unit": "/month",
            "annual_unit": "/year",
            "features": [
                "PeachBook online booking",
                "Coach Peach",
            ],
        },
        "packages": {
            "top_statement_1": "Built for independent businesses.",
            "top_statement_2": "",
            "button_text": "Start 10-Day Free Trial",
            "bottom_heading": "",
            "bottom_statement": "",
            "feature_headings": [],
        },
        "pricing": {
            "top_statement_1": "Simple monthly and annual options.",
            "top_statement_2": "",
            "button_text": "Start 10-Day Free Trial",
            "bottom_heading": "",
            "bottom_statement": "",
        },
    }


def fake_connection(current_draft=None):
    connection = MagicMock()
    connection.autocommit = False

    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [
        (current_draft,),
        (3,),
        (101,),
    ]
    cursor.rowcount = 1

    return connection, cursor


def save(connection, content=None, section="product.solo",
         expected=None):
    return save_section_draft(
        connection,
        section_key=section,
        content=valid_product() if content is None else content,
        actor_id=9,
        expected_draft_revision_id=expected,
    )


class ProductDraftSaveTests(unittest.TestCase):

    def test_all_four_product_sections_can_save(self):
        for section in (
            "product.solo",
            "product.peachpos",
            "product.team",
            "product.collective",
        ):
            with self.subTest(section=section):
                connection, cursor = fake_connection()
                result = save(connection, section=section)

                self.assertEqual(result["page_key"], section)
                connection.commit.assert_called_once()
                connection.rollback.assert_not_called()

    def test_saved_snapshot_preserves_shared_and_both_pages(self):
        connection, cursor = fake_connection()
        result = save(connection)

        self.assertEqual(
            set(result["content"]),
            {"shared", "packages", "pricing"},
        )
        self.assertEqual(
            result["content"]["shared"]["features"],
            ["PeachBook online booking", "Coach Peach"],
        )
        self.assertEqual(
            result["content"]["pricing"]["button_text"],
            "Start 10-Day Free Trial",
        )

    def test_update_is_draft_only(self):
        connection, cursor = fake_connection()
        save(connection)

        statements = [
            str(call.args[0]).lower()
            for call in cursor.execute.call_args_list
        ]

        updates = [
            sql for sql in statements
            if "update psp_marketing_page_state" in sql
        ]

        self.assertEqual(len(updates), 1)
        self.assertIn("set draft_revision_id", updates[0])
        self.assertNotIn("published_revision_id", updates[0])

    def test_save_is_single_transaction(self):
        connection, cursor = fake_connection()
        save(connection)

        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()

    def test_existing_draft_revision_supported(self):
        connection, cursor = fake_connection(current_draft=48)
        result = save(connection, expected=48)

        self.assertEqual(result["revision_id"], 101)
        self.assertEqual(result["revision_number"], 3)
        connection.commit.assert_called_once()

    def test_conflicting_revision_rolls_back(self):
        connection, cursor = fake_connection(current_draft=48)

        with self.assertRaises(MarketingCMSConflict):
            save(connection, expected=47)

        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()

    def test_invalid_status_rejected_before_database(self):
        payload = valid_product()
        payload["shared"]["status"] = "unknown"

        connection, cursor = fake_connection()

        with self.assertRaises(MarketingContentError):
            save(connection, content=payload)

        cursor.execute.assert_not_called()

    def test_html_rejected_before_database(self):
        payload = valid_product()
        payload["shared"]["name"] = "<script>bad</script>"

        connection, cursor = fake_connection()

        with self.assertRaises(MarketingContentError):
            save(connection, content=payload)

        cursor.execute.assert_not_called()

    def test_invalid_feature_rejected_before_database(self):
        payload = valid_product()
        payload["shared"]["features"] = [""]

        connection, cursor = fake_connection()

        with self.assertRaises(MarketingContentError):
            save(connection, content=payload)

        cursor.execute.assert_not_called()

    def test_invalid_pricing_content_rejected(self):
        payload = valid_product()
        payload["pricing"]["button_text"] = ""

        connection, cursor = fake_connection()

        with self.assertRaises(MarketingContentError):
            save(connection, content=payload)

        cursor.execute.assert_not_called()

    def test_invalid_packages_feature_heading_rejected(self):
        payload = valid_product()
        payload["packages"]["feature_headings"] = [{
            "before_feature": 99,
            "text": "Invalid heading position",
        }]

        connection, cursor = fake_connection()

        with self.assertRaises(MarketingContentError):
            save(connection, content=payload)

        cursor.execute.assert_not_called()

    def test_autocommit_rejected(self):
        connection, cursor = fake_connection()
        connection.autocommit = True

        with self.assertRaises(MarketingCMSConfigurationError):
            save(connection)

        cursor.execute.assert_not_called()

    def test_non_product_section_not_implicitly_enabled(self):
        connection, cursor = fake_connection()

        with self.assertRaises(MarketingCMSSectionError):
            save(
                connection,
                section="marketing.benefits",
            )

        cursor.execute.assert_not_called()

    def test_valid_save_returns_correct_revision(self):
        connection, cursor = fake_connection()
        payload = valid_product()
        result = save(connection, content=payload)

        self.assertEqual(result["revision_id"], 101)
        self.assertEqual(result["revision_number"], 3)
        self.assertEqual(result["page_key"], "product.solo")
        self.assertEqual(
            result["content"]["shared"]["monthly_price"],
            "$49",
        )


if __name__ == "__main__":
    unittest.main()
