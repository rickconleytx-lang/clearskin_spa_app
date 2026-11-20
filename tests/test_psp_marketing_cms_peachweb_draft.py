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
    save_section_draft,
)


def valid_content():
    return {
        "showcase": {
            "image_public_id": "",
            "image_url": "",
            "image_alt": "",
            "caption": "See what PeachWeb can do.\nBuilt for business.",
        }
    }


def content_with_image():
    content = valid_content()

    public_id = (
        "peach-suite-pro/marketing-cms/showcases/"
        "peachweb/" + "a" * 32
    )

    content["showcase"].update({
        "image_public_id": public_id,
        "image_url": (
            "https://res.cloudinary.com/example/image/upload/"
            f"v1234567890/{public_id}.png"
        ),
        "image_alt": "Example PeachWeb customer website",
    })

    return content


def fake_connection(rows):
    conn = MagicMock()
    conn.autocommit = False

    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = rows
    cursor.rowcount = 1

    return conn, cursor


class PeachWebDraftTests(unittest.TestCase):

    def test_saves_first_independent_draft(self):
        conn, cursor = fake_connection([
            (None,),
            (1,),
            (601,),
        ])

        content = valid_content()

        result = save_section_draft(
            conn,
            section_key="home.peachweb",
            content=content,
            actor_id=1,
            expected_draft_revision_id=None,
        )

        self.assertEqual(result["page_key"], "home.peachweb")
        self.assertEqual(result["revision_id"], 601)
        self.assertEqual(result["revision_number"], 1)
        self.assertEqual(result["content"], content)

        calls = cursor.execute.call_args_list

        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0].args[1], ("home.peachweb",))
        self.assertEqual(calls[1].args[1], ("home.peachweb",))
        self.assertEqual(calls[2].args[1][0], "home.peachweb")
        self.assertEqual(calls[3].args[1], (601, "home.peachweb"))

        self.assertIn("FOR UPDATE", calls[0].args[0])
        self.assertNotIn(
            "published_revision_id",
            calls[3].args[0],
        )

        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_saves_image_reference_and_multiline_caption(self):
        conn, _ = fake_connection([
            (None,),
            (1,),
            (602,),
        ])

        content = content_with_image()

        result = save_section_draft(
            conn,
            section_key="home.peachweb",
            content=content,
            actor_id=1,
            expected_draft_revision_id=None,
        )

        showcase = result["content"]["showcase"]

        self.assertEqual(
            showcase["image_public_id"],
            content["showcase"]["image_public_id"],
        )
        self.assertEqual(
            showcase["image_url"],
            content["showcase"]["image_url"],
        )
        self.assertEqual(
            showcase["caption"].count("\n"), 1
        )

        conn.commit.assert_called_once()

    def test_saves_next_peachweb_revision(self):
        conn, _ = fake_connection([
            (601,),
            (2,),
            (603,),
        ])

        result = save_section_draft(
            conn,
            section_key="home.peachweb",
            content=valid_content(),
            actor_id=1,
            expected_draft_revision_id=601,
        )

        self.assertEqual(result["revision_number"], 2)
        self.assertEqual(result["revision_id"], 603)
        conn.commit.assert_called_once()

    def test_stale_peachweb_draft_is_rejected(self):
        conn, cursor = fake_connection([
            (603,),
        ])

        with self.assertRaises(MarketingCMSConflict):
            save_section_draft(
                conn,
                section_key="home.peachweb",
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=601,
            )

        self.assertEqual(cursor.execute.call_count, 1)
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_missing_section_state_rolls_back(self):
        conn, _ = fake_connection([None])

        with self.assertRaises(MarketingCMSNotFound):
            save_section_draft(
                conn,
                section_key="home.peachweb",
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_invalid_content_rejected_before_sql(self):
        conn, _ = fake_connection([])

        with self.assertRaises(MarketingContentError):
            save_section_draft(
                conn,
                section_key="home.peachweb",
                content={"showcase": {"caption": "Incomplete"}},
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_home_hero_content_cannot_replace_peachweb(self):
        conn, _ = fake_connection([])

        with self.assertRaises(MarketingContentError):
            save_section_draft(
                conn,
                section_key="home.peachweb",
                content={"hero": {}},
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_peachbook_still_requires_own_validator(self):
        conn, _ = fake_connection([])

        with self.assertRaises(MarketingCMSSectionError):
            save_section_draft(
                conn,
                section_key="home.peachbook",
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_unknown_section_rejected_before_sql(self):
        conn, _ = fake_connection([])

        with self.assertRaises(MarketingCMSSectionError):
            save_section_draft(
                conn,
                section_key="unknown.section",
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_autocommit_is_rejected(self):
        conn, _ = fake_connection([])
        conn.autocommit = True

        with self.assertRaises(MarketingCMSConfigurationError):
            save_section_draft(
                conn,
                section_key="home.peachweb",
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()
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
                section_key="home.peachweb",
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=None,
            )

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_invalid_actor_rejected_before_sql(self):
        conn, _ = fake_connection([])

        with self.assertRaises(ValueError):
            save_section_draft(
                conn,
                section_key="home.peachweb",
                content=valid_content(),
                actor_id=0,
                expected_draft_revision_id=None,
            )

        conn.cursor.assert_not_called()

    def test_invalid_revision_rejected_before_sql(self):
        conn, _ = fake_connection([])

        with self.assertRaises(ValueError):
            save_section_draft(
                conn,
                section_key="home.peachweb",
                content=valid_content(),
                actor_id=1,
                expected_draft_revision_id=-1,
            )

        conn.cursor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
