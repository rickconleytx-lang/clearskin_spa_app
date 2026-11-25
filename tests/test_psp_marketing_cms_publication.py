import unittest
from unittest.mock import MagicMock

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
    MarketingCMSConfigurationError,
    MarketingCMSNotFound,
)
from services.psp_marketing_cms_publication import (
    MarketingCMSUnpublishedRevision,
    publish_home_draft,
    restore_home_revision,
)


def valid_content():
    return {
        "hero": {
            "primary_button_text": "Start Free Trial",
            "secondary_button_text": "View Pricing",
            "pricing_sentence": "Review our subscription options.",
        }
    }


def fake_connection(rows):
    conn = MagicMock()
    conn.autocommit = False

    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = rows
    cursor.rowcount = 1

    return conn, cursor


class MarketingPublicationTests(unittest.TestCase):

    def test_first_publish(self):
        conn, cursor = fake_connection([
            (11, None),
            (valid_content(),),
            (101,),
        ])

        result = publish_home_draft(
            conn,
            actor_id=1,
            expected_draft_revision_id=11,
            expected_published_revision_id=None,
        )

        self.assertEqual(result["revision_id"], 11)
        self.assertIsNone(result["previous_revision_id"])
        self.assertEqual(result["action"], "publish")
        self.assertEqual(result["publication_event_id"], 101)
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

        statements = [
            call.args[0]
            for call in cursor.execute.call_args_list
        ]
        self.assertEqual(len(statements), 4)
        self.assertIn("FOR UPDATE", statements[0])
        self.assertIn(
            "UPDATE psp_marketing_page_state",
            statements[2],
        )
        self.assertNotIn(
            "draft_revision_id",
            statements[2],
        )
        self.assertIn(
            "INSERT INTO psp_marketing_publication_events",
            statements[3],
        )

    def test_publish_newer_draft(self):
        conn, _ = fake_connection([
            (12, 11),
            (valid_content(),),
            (102,),
        ])

        result = publish_home_draft(
            conn,
            actor_id=1,
            expected_draft_revision_id=12,
            expected_published_revision_id=11,
        )

        self.assertEqual(result["previous_revision_id"], 11)
        self.assertEqual(result["revision_id"], 12)
        conn.commit.assert_called_once()

    def test_stale_draft_rejected(self):
        conn, cursor = fake_connection([(12, 11)])

        with self.assertRaises(MarketingCMSConflict):
            publish_home_draft(
                conn,
                actor_id=1,
                expected_draft_revision_id=10,
                expected_published_revision_id=11,
            )

        self.assertEqual(cursor.execute.call_count, 1)
        conn.rollback.assert_called_once()

    def test_stale_publication_rejected(self):
        conn, _ = fake_connection([(12, 11)])

        with self.assertRaises(MarketingCMSConflict):
            publish_home_draft(
                conn,
                actor_id=1,
                expected_draft_revision_id=12,
                expected_published_revision_id=None,
            )

        conn.rollback.assert_called_once()

    def test_publish_without_draft_rejected(self):
        conn, _ = fake_connection([(None, None)])

        with self.assertRaises(MarketingCMSConflict):
            publish_home_draft(
                conn,
                actor_id=1,
                expected_draft_revision_id=9,
                expected_published_revision_id=None,
            )

        conn.commit.assert_not_called()

    def test_republishing_same_revision_rejected(self):
        conn, _ = fake_connection([(11, 11)])

        with self.assertRaises(MarketingCMSConflict):
            publish_home_draft(
                conn,
                actor_id=1,
                expected_draft_revision_id=11,
                expected_published_revision_id=11,
            )

        conn.rollback.assert_called_once()

    def test_restore_previously_published(self):
        conn, cursor = fake_connection([
            (15, 12),
            (1,),
            (valid_content(),),
            (200,),
        ])

        result = restore_home_revision(
            conn,
            actor_id=1,
            revision_id=8,
            expected_published_revision_id=12,
        )

        self.assertEqual(result["action"], "restore")
        self.assertEqual(result["revision_id"], 8)
        self.assertEqual(result["previous_revision_id"], 12)
        conn.commit.assert_called_once()

        statements = [
            call.args[0]
            for call in cursor.execute.call_args_list
        ]
        self.assertEqual(len(statements), 5)
        self.assertIn(
            "psp_marketing_publication_events",
            statements[1],
        )
        self.assertIn(
            "UPDATE psp_marketing_page_state",
            statements[3],
        )
        self.assertNotIn(
            "draft_revision_id",
            statements[3],
        )

    def test_restore_unpublished_revision_rejected(self):
        conn, cursor = fake_connection([
            (15, 12),
            None,
        ])

        with self.assertRaises(MarketingCMSUnpublishedRevision):
            restore_home_revision(
                conn,
                actor_id=1,
                revision_id=9,
                expected_published_revision_id=12,
            )

        self.assertEqual(cursor.execute.call_count, 2)
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_restore_current_revision_rejected(self):
        conn, _ = fake_connection([(15, 12)])

        with self.assertRaises(MarketingCMSConflict):
            restore_home_revision(
                conn,
                actor_id=1,
                revision_id=12,
                expected_published_revision_id=12,
            )

        conn.rollback.assert_called_once()

    def test_missing_page_rejected(self):
        conn, _ = fake_connection([None])

        with self.assertRaises(MarketingCMSNotFound):
            publish_home_draft(
                conn,
                actor_id=1,
                expected_draft_revision_id=11,
                expected_published_revision_id=None,
            )

        conn.rollback.assert_called_once()

    def test_invalid_actor_rejected_before_sql(self):
        for actor in (None, 0, True, "1"):
            conn, _ = fake_connection([])

            with self.subTest(actor=actor):
                with self.assertRaises(ValueError):
                    publish_home_draft(
                        conn,
                        actor_id=actor,
                        expected_draft_revision_id=11,
                        expected_published_revision_id=None,
                    )

                conn.cursor.assert_not_called()

    def test_invalid_revision_rejected_before_sql(self):
        for target in (0, -1, True, "8"):
            conn, _ = fake_connection([])

            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    restore_home_revision(
                        conn,
                        actor_id=1,
                        revision_id=target,
                        expected_published_revision_id=None,
                    )

                conn.cursor.assert_not_called()

    def test_invalid_expected_published_id_rejected(self):
        conn, _ = fake_connection([])

        with self.assertRaises(ValueError):
            publish_home_draft(
                conn,
                actor_id=1,
                expected_draft_revision_id=11,
                expected_published_revision_id="10",
            )

        conn.cursor.assert_not_called()

    def test_autocommit_rejected(self):
        conn, _ = fake_connection([])
        conn.autocommit = True

        with self.assertRaises(
            MarketingCMSConfigurationError
        ):
            publish_home_draft(
                conn,
                actor_id=1,
                expected_draft_revision_id=11,
                expected_published_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_invalid_stored_content_rejected(self):
        conn, _ = fake_connection([
            (11, None),
            ({"hero": {}},),
        ])

        with self.assertRaises(MarketingContentError):
            publish_home_draft(
                conn,
                actor_id=1,
                expected_draft_revision_id=11,
                expected_published_revision_id=None,
            )

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_failed_update_rolls_back(self):
        conn, cursor = fake_connection([
            (11, None),
            (valid_content(),),
        ])
        cursor.execute.side_effect = [
            None,
            None,
            RuntimeError("Simulated update failure"),
        ]

        with self.assertRaises(RuntimeError):
            publish_home_draft(
                conn,
                actor_id=1,
                expected_draft_revision_id=11,
                expected_published_revision_id=None,
            )

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_failed_audit_insert_rolls_back(self):
        conn, cursor = fake_connection([
            (11, None),
            (valid_content(),),
        ])
        cursor.execute.side_effect = [
            None,
            None,
            None,
            RuntimeError("Simulated audit failure"),
        ]

        with self.assertRaises(RuntimeError):
            publish_home_draft(
                conn,
                actor_id=1,
                expected_draft_revision_id=11,
                expected_published_revision_id=None,
            )

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
