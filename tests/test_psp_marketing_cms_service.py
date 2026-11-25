import unittest
from services.psp_marketing_cms_sections import MarketingCMSSectionError
from unittest.mock import MagicMock

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
    MarketingCMSConfigurationError,
    MarketingCMSNotFound,
    load_home_state,
    load_section_state,
    save_home_draft,
    save_section_draft,
)


def valid_content():
    return {
        "hero": {
            "primary_button_text": "Start Your Free Trial",
            "secondary_button_text": "View Pricing",
            "pricing_sentence": "See current subscription pricing.",
        }
    }


def fake_connection(rows):
    conn = MagicMock()
    conn.autocommit = False

    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = rows
    cursor.rowcount = 1

    return conn, cursor


class MarketingCMSServiceTests(unittest.TestCase):

    def test_loads_unpublished_page(self):
        conn, cursor = fake_connection([
            (None, None, None, None)
        ])

        state = load_home_state(conn)

        self.assertIsNone(state["draft_revision_id"])
        self.assertIsNone(state["published_revision_id"])
        conn.commit.assert_not_called()
        self.assertEqual(cursor.execute.call_count, 1)

    def test_loads_separate_draft_and_published(self):
        conn, _ = fake_connection([
            (9, {"hero": {"draft": "new"}},
             5, {"hero": {"published": "old"}})
        ])

        state = load_home_state(conn)

        self.assertEqual(state["draft_revision_id"], 9)
        self.assertEqual(state["published_revision_id"], 5)
        self.assertNotEqual(
            state["draft_content"],
            state["published_content"],
        )

    def test_missing_page_raises(self):
        conn, _ = fake_connection([None])

        with self.assertRaises(MarketingCMSNotFound):
            load_home_state(conn)

    def test_save_first_draft(self):
        conn, cursor = fake_connection([
            (None,),
            (1,),
            (42,),
        ])

        result = save_home_draft(
            conn,
            content=valid_content(),
            actor_id=1,
            expected_draft_revision_id=None,
        )

        self.assertEqual(result["revision_id"], 42)
        self.assertEqual(result["revision_number"], 1)
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

        statements = [
            call.args[0]
            for call in cursor.execute.call_args_list
        ]

        self.assertEqual(len(statements), 4)
        self.assertIn("FOR UPDATE", statements[0])
        self.assertIn(
            "INSERT INTO psp_marketing_revisions",
            statements[2],
        )
        self.assertIn(
            "UPDATE psp_marketing_page_state",
            statements[3],
        )
        self.assertNotIn(
            "published_revision_id",
            statements[3],
        )

    def test_save_following_draft(self):
        conn, _ = fake_connection([
            (42,),
            (2,),
            (43,),
        ])

        result = save_home_draft(
            conn,
            content=valid_content(),
            actor_id=1,
            expected_draft_revision_id=42,
        )

        self.assertEqual(result["revision_id"], 43)
        self.assertEqual(result["revision_number"], 2)
        conn.commit.assert_called_once()

    def test_stale_draft_is_rejected(self):
        conn, cursor = fake_connection([
            (43,),
        ])

        with self.assertRaises(MarketingCMSConflict):
            save_home_draft(
                conn,
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=42,
            )

        self.assertEqual(cursor.execute.call_count, 1)
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_missing_page_rolls_back(self):
        conn, _ = fake_connection([None])

        with self.assertRaises(MarketingCMSNotFound):
            save_home_draft(
                conn,
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.rollback.assert_called_once()

    def test_invalid_actor_rejected_before_sql(self):
        conn, _ = fake_connection([])

        for actor_id in (None, 0, True, "1"):
            with self.subTest(actor_id=actor_id):
                with self.assertRaises(ValueError):
                    save_home_draft(
                        conn,
                        content=valid_content(),
                        actor_id=actor_id,
                        expected_draft_revision_id=None,
                    )

        conn.cursor.assert_not_called()

    def test_invalid_revision_rejected_before_sql(self):
        conn, _ = fake_connection([])

        for revision_id in (0, -1, True, "2"):
            with self.subTest(revision_id=revision_id):
                with self.assertRaises(ValueError):
                    save_home_draft(
                        conn,
                        content=valid_content(),
                        actor_id=1,
                        expected_draft_revision_id=revision_id,
                    )

        conn.cursor.assert_not_called()

    def test_invalid_content_rejected_before_sql(self):
        conn, _ = fake_connection([])

        with self.assertRaises(MarketingContentError):
            save_home_draft(
                conn,
                content={"hero": {}},
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_autocommit_rejected(self):
        conn, _ = fake_connection([])
        conn.autocommit = True

        with self.assertRaises(MarketingCMSConfigurationError):
            save_home_draft(
                conn,
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_database_failure_rolls_back(self):
        conn, cursor = fake_connection([
            (None,),
            (1,),
        ])
        cursor.execute.side_effect = [
            None, None, RuntimeError("Simulated failure")
        ]

        with self.assertRaises(RuntimeError):
            save_home_draft(
                conn,
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()



class MarketingCMSSectionLoadingTests(unittest.TestCase):

    def test_loads_independent_registered_section(self):
        conn, cursor = fake_connection([
            (
                12,
                {"promotion": {"title": "Draft"}},
                9,
                {"promotion": {"title": "Published"}},
            )
        ])

        state = load_section_state(
            conn,
            section_key="home.promo",
        )

        self.assertEqual(state["draft_revision_id"], 12)
        self.assertEqual(state["published_revision_id"], 9)

        self.assertEqual(
            cursor.execute.call_args.args[1],
            ("home.promo",),
        )

        conn.commit.assert_not_called()

    def test_rejects_unknown_section_before_sql(self):
        conn, _ = fake_connection([])

        with self.assertRaises(MarketingCMSSectionError):
            load_section_state(
                conn,
                section_key="unsupported.section",
            )

        conn.cursor.assert_not_called()



def promotion_content():
    return {
        "promotion": {
            "product_label": "Solo",
            "headline": "One business.\nOne owner.\nOne connected system.",
            "monthly_price": "$49",
            "pricing_description": (
                "Or $490/year. Start with a 10-day free trial."
            ),
            "features": [
                "Client Management",
                "Appointment Calendar",
                "PeachBook",
                "PeachWeb",
                "Income & Expenses",
                "Inventory",
                "Coach Peach",
                "Square Integration",
                "Import & Export",
            ],
        }
    }


class MarketingCMSSectionDraftTests(unittest.TestCase):

    def test_saves_first_promotion_draft(self):
        conn, cursor = fake_connection([
            (None,),
            (1,),
            (501,),
        ])

        result = save_section_draft(
            conn,
            section_key="home.promo",
            content=promotion_content(),
            actor_id=1,
            expected_draft_revision_id=None,
        )

        self.assertEqual(result["page_key"], "home.promo")
        self.assertEqual(result["revision_id"], 501)
        self.assertEqual(result["revision_number"], 1)
        self.assertIn(
            "\n",
            result["content"]["promotion"]["headline"],
        )

        calls = cursor.execute.call_args_list
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0].args[1], ("home.promo",))
        self.assertEqual(calls[1].args[1], ("home.promo",))
        self.assertEqual(calls[2].args[1][0], "home.promo")
        self.assertEqual(calls[3].args[1], (501, "home.promo"))
        self.assertNotIn(
            "published_revision_id",
            calls[3].args[0],
        )

        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_saves_following_promotion_revision(self):
        conn, _ = fake_connection([
            (501,),
            (2,),
            (502,),
        ])

        result = save_section_draft(
            conn,
            section_key="home.promo",
            content=promotion_content(),
            actor_id=1,
            expected_draft_revision_id=501,
        )

        self.assertEqual(result["revision_number"], 2)
        self.assertEqual(result["revision_id"], 502)
        conn.commit.assert_called_once()

    def test_rejects_stale_promotion_draft(self):
        conn, cursor = fake_connection([(502,)])

        with self.assertRaises(MarketingCMSConflict):
            save_section_draft(
                conn,
                section_key="home.promo",
                content=promotion_content(),
                actor_id=1,
                expected_draft_revision_id=501,
            )

        self.assertEqual(cursor.execute.call_count, 1)
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_missing_promotion_state_rolls_back(self):
        conn, _ = fake_connection([None])

        with self.assertRaises(MarketingCMSNotFound):
            save_section_draft(
                conn,
                section_key="home.promo",
                content=promotion_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_unknown_section_rejected_before_sql(self):
        conn, _ = fake_connection([])

        with self.assertRaises(MarketingCMSSectionError):
            save_section_draft(
                conn,
                section_key="not.registered",
                content=promotion_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_invalid_product_rejected_before_sql(self):
        from services.psp_marketing_cms_content import (
            MarketingContentError,
        )
        conn, _ = fake_connection([])

        with self.assertRaises(MarketingContentError):
            save_section_draft(
                conn,
                section_key="product.solo",
                content=promotion_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_invalid_promotion_rejected_before_sql(self):
        conn, _ = fake_connection([])

        with self.assertRaises(MarketingContentError):
            save_section_draft(
                conn,
                section_key="home.promo",
                content={"promotion": {}},
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_home_content_cannot_be_saved_as_promotion(self):
        conn, _ = fake_connection([])

        with self.assertRaises(MarketingContentError):
            save_section_draft(
                conn,
                section_key="home.promo",
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_promotion_requires_transaction(self):
        conn, _ = fake_connection([])
        conn.autocommit = True

        with self.assertRaises(MarketingCMSConfigurationError):
            save_section_draft(
                conn,
                section_key="home.promo",
                content=promotion_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
