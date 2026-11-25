import unittest
from unittest.mock import MagicMock

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_sections import (
    MarketingCMSSectionError,
)
from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
    MarketingCMSConfigurationError,
    MarketingCMSNotFound,
)
from services.psp_marketing_cms_showcase_publication import (
    publish_showcase_draft,
)


def content():
    return {
        "showcase": {
            "image_public_id": "",
            "image_url": "",
            "image_alt": "",
            "caption": "A private draft caption.",
        }
    }


def fake_connection(responses):
    conn = MagicMock()
    conn.autocommit = False

    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = responses
    cur.rowcount = 1

    return conn, cur


def publish(conn, key="home.peachweb", draft=11, published=None):
    return publish_showcase_draft(
        conn,
        section_key=key,
        actor_id=7,
        expected_draft_revision_id=draft,
        expected_published_revision_id=published,
    )


class ShowcasePublicationTests(unittest.TestCase):

    def test_peachweb_first_publish(self):
        conn, cur = fake_connection([
            (11, None),
            (content(),),
            (501,),
        ])

        result = publish(conn)

        self.assertEqual(result["page_key"], "home.peachweb")
        self.assertEqual(result["revision_id"], 11)
        self.assertIsNone(result["previous_revision_id"])
        self.assertEqual(result["publication_event_id"], 501)

        calls = cur.execute.call_args_list

        self.assertEqual(len(calls), 4)
        self.assertIn("FOR UPDATE", calls[0].args[0])
        self.assertEqual(calls[0].args[1], ("home.peachweb",))
        self.assertEqual(calls[1].args[1], ("home.peachweb", 11))
        self.assertEqual(calls[2].args[1], (11, 7, "home.peachweb"))
        self.assertEqual(
            calls[3].args[1],
            ("home.peachweb", 11, None, "publish", 7),
        )

        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_peachbook_publishes_only_its_section(self):
        conn, cur = fake_connection([
            (21, 8),
            (content(),),
            (502,),
        ])

        result = publish(
            conn,
            key="home.peachbook",
            draft=21,
            published=8,
        )

        self.assertEqual(result["page_key"], "home.peachbook")
        self.assertEqual(result["previous_revision_id"], 8)

        for call in cur.execute.call_args_list:
            self.assertIn(
                "home.peachbook",
                call.args[1],
            )
            self.assertNotIn(
                "home.peachweb",
                call.args[1],
            )

        conn.commit.assert_called_once()

    def test_stale_draft_is_rejected(self):
        conn, cur = fake_connection([(12, None)])

        with self.assertRaises(MarketingCMSConflict):
            publish(conn)

        self.assertEqual(cur.execute.call_count, 1)
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_changed_publication_is_rejected(self):
        conn, cur = fake_connection([(11, 9)])

        with self.assertRaises(MarketingCMSConflict):
            publish(conn)

        self.assertEqual(cur.execute.call_count, 1)
        conn.rollback.assert_called_once()

    def test_duplicate_publication_is_rejected(self):
        conn, _ = fake_connection([(11, 11)])

        with self.assertRaises(MarketingCMSConflict):
            publish(conn, published=11)

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_missing_section_state_is_rejected(self):
        conn, _ = fake_connection([None])

        with self.assertRaises(MarketingCMSNotFound):
            publish(conn)

        conn.rollback.assert_called_once()

    def test_missing_revision_is_rejected(self):
        conn, _ = fake_connection([
            (11, None),
            None,
        ])

        with self.assertRaises(MarketingCMSNotFound):
            publish(conn)

        conn.rollback.assert_called_once()

    def test_invalid_stored_content_is_rejected(self):
        conn, cur = fake_connection([
            (11, None),
            ({"showcase": {"caption": 55}},),
        ])

        with self.assertRaises(MarketingContentError):
            publish(conn)

        self.assertEqual(cur.execute.call_count, 2)
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_cross_showcase_image_is_rejected(self):
        public_id = (
            "peach-suite-pro/marketing-cms/showcases/"
            "peachweb/" + "a" * 32
        )

        invalid = content()
        invalid["showcase"].update({
            "image_public_id": public_id,
            "image_url": (
                "https://res.cloudinary.com/example/image/upload/"
                f"v1234567890/{public_id}.jpg"
            ),
            "image_alt": "PeachWeb website picture",
        })

        conn, cur = fake_connection([
            (11, None),
            (invalid,),
        ])

        with self.assertRaises(MarketingContentError):
            publish(conn, key="home.peachbook")

        self.assertEqual(cur.execute.call_count, 2)
        conn.rollback.assert_called_once()

    def test_failed_publication_update_rolls_back(self):
        conn, cur = fake_connection([
            (11, None),
            (content(),),
        ])
        cur.rowcount = 0

        with self.assertRaises(MarketingCMSNotFound):
            publish(conn)

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_failed_audit_insert_rolls_back(self):
        conn, cur = fake_connection([
            (11, None),
            (content(),),
        ])

        cur.execute.side_effect = [
            None,
            None,
            None,
            RuntimeError("Simulated audit insert failure"),
        ]

        with self.assertRaises(RuntimeError):
            publish(conn)

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_invalid_ids_rejected_before_sql(self):
        for field, bad in (
            ("actor_id", True),
            ("expected_draft_revision_id", None),
            ("expected_draft_revision_id", -1),
            ("expected_published_revision_id", 0),
            ("expected_published_revision_id", 2**63),
        ):
            with self.subTest(field=field, bad=bad):
                conn, _ = fake_connection([])

                args = {
                    "section_key": "home.peachweb",
                    "actor_id": 7,
                    "expected_draft_revision_id": 11,
                    "expected_published_revision_id": None,
                }
                args[field] = bad

                with self.assertRaises(ValueError):
                    publish_showcase_draft(conn, **args)

                conn.cursor.assert_not_called()
                conn.commit.assert_not_called()

    def test_other_sections_cannot_be_published(self):
        for key in (
            "home",
            "home.promo",
            "product.solo",
            "unknown.section",
        ):
            with self.subTest(key=key):
                conn, _ = fake_connection([])

                with self.assertRaises(MarketingCMSSectionError):
                    publish(conn, key=key)

                conn.cursor.assert_not_called()
                conn.commit.assert_not_called()

    def test_autocommit_is_rejected(self):
        conn, _ = fake_connection([])
        conn.autocommit = True

        with self.assertRaises(MarketingCMSConfigurationError):
            publish(conn)

        conn.cursor.assert_not_called()
        conn.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
