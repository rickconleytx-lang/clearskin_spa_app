"""Public introduction reader tests using fake database connections."""

import unittest

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_public_intro import (
    load_published_intro,
)
from services.psp_marketing_cms_sections import (
    MarketingCMSSectionError,
)
from services.psp_marketing_cms_service import (
    MarketingCMSNotFound,
)


def content(heading="Launch Special", paragraph="Use LAUNCH10 to save."):
    return {
        "intro": {
            "heading": heading,
            "paragraph": paragraph,
        }
    }


class FakeCursor:

    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        statement = " ".join(sql.lower().split())

        if (
            not statement.startswith("select ")
            or "from psp_marketing_page_state" not in statement
            or "where state.page_key = %s" not in statement
            or len(params) != 1
        ):
            raise AssertionError(
                "Unexpected or unsafe SQL: " + statement
            )

        self.connection.queries.append((statement, params))

    def fetchone(self):
        return self.connection.row


class FakeConnection:

    def __init__(self, row=None):
        self.row = (
            (10, content("Unpublished Draft"), 9, content())
            if row is None else row
        )
        self.queries = []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


class PublicIntroductionReaderTests(unittest.TestCase):

    def test_packages_published_intro(self):
        conn = FakeConnection()

        intro = load_published_intro(
            conn, section_key="packages.intro"
        )

        self.assertEqual(intro["heading"], "Launch Special")
        self.assertEqual(intro["paragraph"], "Use LAUNCH10 to save.")

    def test_pricing_published_intro(self):
        conn = FakeConnection(
            row=(None, None, 15, content("Pricing Offer"))
        )

        intro = load_published_intro(
            conn, section_key="pricing.intro"
        )

        self.assertEqual(intro["heading"], "Pricing Offer")

    def test_packages_and_pricing_are_independent(self):
        for section in ("packages.intro", "pricing.intro"):
            with self.subTest(section=section):
                conn = FakeConnection()

                load_published_intro(
                    conn, section_key=section
                )

                self.assertEqual(
                    conn.queries[0][1],
                    (section,),
                )

    def test_newer_draft_is_ignored(self):
        conn = FakeConnection(
            row=(
                20,
                content("PRIVATE UNPUBLISHED DRAFT"),
                9,
                content("Published Promotion"),
            )
        )

        intro = load_published_intro(
            conn, section_key="packages.intro"
        )

        self.assertEqual(
            intro["heading"],
            "Published Promotion",
        )
        self.assertNotIn(
            "PRIVATE UNPUBLISHED DRAFT",
            str(intro),
        )

    def test_draft_only_returns_no_public_override(self):
        conn = FakeConnection(
            row=(20, content("Private Draft"), None, None)
        )

        self.assertIsNone(
            load_published_intro(
                conn, section_key="packages.intro"
            )
        )

    def test_no_revisions_returns_no_public_override(self):
        conn = FakeConnection(
            row=(None, None, None, None)
        )

        self.assertIsNone(
            load_published_intro(
                conn, section_key="pricing.intro"
            )
        )

    def test_same_draft_and_published_id_is_valid(self):
        conn = FakeConnection(
            row=(9, content(), 9, content())
        )

        intro = load_published_intro(
            conn, section_key="packages.intro"
        )

        self.assertEqual(intro["heading"], "Launch Special")

    def test_missing_state_is_rejected(self):
        conn = FakeConnection()
        conn.row = None

        with self.assertRaises(MarketingCMSNotFound):
            load_published_intro(
                conn, section_key="packages.intro"
            )

    def test_script_in_heading_is_rejected(self):
        conn = FakeConnection(
            row=(
                None,
                None,
                9,
                content("<script>alert(1)</script>"),
            )
        )

        with self.assertRaises(MarketingContentError):
            load_published_intro(
                conn, section_key="packages.intro"
            )

    def test_html_in_paragraph_is_rejected(self):
        conn = FakeConnection(
            row=(
                None,
                None,
                9,
                content(
                    "Valid Heading",
                    "<img src=x onerror=alert(1)>",
                ),
            )
        )

        with self.assertRaises(MarketingContentError):
            load_published_intro(
                conn, section_key="packages.intro"
            )

    def test_invalid_snapshot_structure_is_rejected(self):
        conn = FakeConnection(
            row=(None, None, 9, {"heading": "Wrong"})
        )

        with self.assertRaises(MarketingContentError):
            load_published_intro(
                conn, section_key="packages.intro"
            )

    def test_published_id_without_content_is_rejected(self):
        conn = FakeConnection(
            row=(None, None, 9, None)
        )

        with self.assertRaises(ValueError):
            load_published_intro(
                conn, section_key="packages.intro"
            )

    def test_published_content_without_id_is_rejected(self):
        conn = FakeConnection(
            row=(None, None, None, content())
        )

        with self.assertRaises(ValueError):
            load_published_intro(
                conn, section_key="packages.intro"
            )

    def test_invalid_published_revision_ids_rejected(self):
        for revision_id in (
            True,
            0,
            -1,
            "9",
            9223372036854775808,
        ):
            with self.subTest(revision_id=revision_id):
                conn = FakeConnection(
                    row=(None, None, revision_id, content())
                )

                with self.assertRaises(ValueError):
                    load_published_intro(
                        conn, section_key="packages.intro"
                    )

    def test_non_intro_section_is_rejected(self):
        conn = FakeConnection()

        with self.assertRaises(MarketingCMSSectionError):
            load_published_intro(
                conn, section_key="home"
            )

        self.assertEqual(conn.queries, [])

    def test_multiline_paragraph_preserved(self):
        conn = FakeConnection(
            row=(
                None,
                None,
                9,
                content(
                    "New Offer",
                    "First line.\nSecond line.",
                ),
            )
        )

        intro = load_published_intro(
            conn, section_key="packages.intro"
        )

        self.assertIn(
            "\n",
            intro["paragraph"],
        )

    def test_promo_code_remains_plain_text(self):
        conn = FakeConnection()

        intro = load_published_intro(
            conn, section_key="packages.intro"
        )

        self.assertIn("LAUNCH10", intro["paragraph"])
        self.assertNotIn("<strong>", intro["paragraph"])

    def test_query_reads_only_requested_section(self):
        conn = FakeConnection()

        load_published_intro(
            conn, section_key="pricing.intro"
        )

        self.assertEqual(len(conn.queries), 1)

        sql, parameters = conn.queries[0]

        self.assertTrue(sql.startswith("select "))
        self.assertEqual(parameters, ("pricing.intro",))
        self.assertIn(
            "published.revision_id",
            sql,
        )

    def test_reader_never_writes_or_commits(self):
        conn = FakeConnection()

        load_published_intro(
            conn, section_key="packages.intro"
        )

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 0)

    def test_reader_does_not_own_connection_cleanup(self):
        conn = FakeConnection()

        load_published_intro(
            conn, section_key="packages.intro"
        )

        self.assertEqual(conn.closes, 0)


if __name__ == "__main__":
    unittest.main()
