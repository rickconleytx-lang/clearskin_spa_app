import unittest
from unittest.mock import MagicMock

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
    MarketingCMSConfigurationError,
    MarketingCMSNotFound,
    save_section_draft,
)


def valid_content():
    return {
        "showcase": {
            "image_public_id": "",
            "image_url": "",
            "image_alt": "",
            "caption": "Book online.\nAnytime, anywhere.",
        }
    }


def image_content():
    content = valid_content()

    public_id = (
        "peach-suite-pro/marketing-cms/showcases/"
        "peachbook/" + "a" * 32
    )

    content["showcase"].update({
        "image_public_id": public_id,
        "image_url": (
            "https://res.cloudinary.com/example/image/upload/"
            f"v1234567890/{public_id}.png"
        ),
        "image_alt": "Customer PeachBook booking page",
    })

    return content


def fake_connection(rows):
    conn = MagicMock()
    conn.autocommit = False

    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = rows
    cursor.rowcount = 1

    return conn, cursor


class PeachBookDraftTests(unittest.TestCase):

    def test_first_draft_is_independent(self):
        conn, cursor = fake_connection([
            (None,),
            (1,),
            (701,),
        ])

        result = save_section_draft(
            conn,
            section_key="home.peachbook",
            content=valid_content(),
            actor_id=1,
            expected_draft_revision_id=None,
        )

        self.assertEqual(result["page_key"], "home.peachbook")
        self.assertEqual(result["revision_id"], 701)
        self.assertEqual(result["revision_number"], 1)

        calls = cursor.execute.call_args_list

        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0].args[1], ("home.peachbook",))
        self.assertEqual(calls[1].args[1], ("home.peachbook",))
        self.assertEqual(calls[2].args[1][0], "home.peachbook")
        self.assertEqual(calls[3].args[1], (701, "home.peachbook"))

        self.assertIn("FOR UPDATE", calls[0].args[0])
        self.assertNotIn(
            "published_revision_id",
            calls[3].args[0],
        )

        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_saves_peachbook_image_and_multiline_caption(self):
        conn, _ = fake_connection([
            (None,),
            (1,),
            (702,),
        ])

        content = image_content()

        result = save_section_draft(
            conn,
            section_key="home.peachbook",
            content=content,
            actor_id=1,
            expected_draft_revision_id=None,
        )

        self.assertEqual(result["content"], content)
        self.assertEqual(
            result["content"]["showcase"]["caption"].count("\n"),
            1,
        )
        conn.commit.assert_called_once()

    def test_following_revision(self):
        conn, _ = fake_connection([
            (702,),
            (2,),
            (703,),
        ])

        result = save_section_draft(
            conn,
            section_key="home.peachbook",
            content=valid_content(),
            actor_id=1,
            expected_draft_revision_id=702,
        )

        self.assertEqual(result["revision_number"], 2)
        self.assertEqual(result["revision_id"], 703)
        conn.commit.assert_called_once()

    def test_stale_revision_rejected(self):
        conn, cursor = fake_connection([
            (703,),
        ])

        with self.assertRaises(MarketingCMSConflict):
            save_section_draft(
                conn,
                section_key="home.peachbook",
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=702,
            )

        self.assertEqual(cursor.execute.call_count, 1)
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_invalid_content_rejected_before_sql(self):
        conn, _ = fake_connection([])

        with self.assertRaises(MarketingContentError):
            save_section_draft(
                conn,
                section_key="home.peachbook",
                content={"showcase": {"caption": "Incomplete"}},
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_peachweb_image_namespace_rejected(self):
        conn, _ = fake_connection([])

        content = image_content()

        for field in ("image_public_id", "image_url"):
            content["showcase"][field] = (
                content["showcase"][field]
                .replace("/peachbook/", "/peachweb/")
            )

        with self.assertRaises(MarketingContentError):
            save_section_draft(
                conn,
                section_key="home.peachbook",
                content=content,
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_autocommit_rejected(self):
        conn, _ = fake_connection([])
        conn.autocommit = True

        with self.assertRaises(MarketingCMSConfigurationError):
            save_section_draft(
                conn,
                section_key="home.peachbook",
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()
        conn.commit.assert_not_called()

    def test_missing_section_state_rolls_back(self):
        conn, _ = fake_connection([None])

        with self.assertRaises(MarketingCMSNotFound):
            save_section_draft(
                conn,
                section_key="home.peachbook",
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_database_failure_rolls_back(self):
        conn, cursor = fake_connection([
            (None,),
            (1,),
        ])

        cursor.execute.side_effect = [
            None,
            None,
            RuntimeError("Simulated insert failure"),
        ]

        with self.assertRaises(RuntimeError):
            save_section_draft(
                conn,
                section_key="home.peachbook",
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
