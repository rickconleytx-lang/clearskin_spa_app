"""Isolated tests for introduction history inspection."""

import unittest

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_history import (
    MarketingCMSHistoryError,
)
from services.psp_marketing_cms_intro_history import (
    load_intro_history,
)
from services.psp_marketing_cms_sections import (
    MarketingCMSSectionError,
)


def content(heading):
    return {
        "intro": {
            "heading": heading,
            "paragraph": "Example promotional paragraph.",
        }
    }


def sample_revisions():
    return [
        (9, 2, content("Original heading"), 9,
         "2026-11-21", None),
        (6, 1, content("TEST heading"), 9,
         "2026-11-21", None),
    ]


def sample_events():
    return [
        (4, 9, None, "publish", 9, "2026-11-21"),
    ]


class FakeCursor:

    def __init__(self, connection):
        self.conn = connection
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        query = " ".join(sql.lower().split())
        self.conn.queries.append((query, params))

        if query.startswith("select draft_revision_id"):
            self.result = self.conn.state

        elif query.startswith("select revision_id,"):
            self.result = self.conn.revisions

        elif query.startswith("select publication_event_id,"):
            self.result = self.conn.events

        else:
            raise AssertionError(
                "Unexpected SQL: " + query
            )

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


class FakeConnection:

    def __init__(
        self,
        *,
        state=(9, 9),
        revisions=None,
        events=None,
    ):
        self.state = state
        self.revisions = (
            sample_revisions()
            if revisions is None else revisions
        )
        self.events = (
            sample_events()
            if events is None else events
        )
        self.queries = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def load(conn, section_key="packages.intro"):
    return load_intro_history(
        conn,
        section_key=section_key,
    )


class IntroductionHistoryTests(unittest.TestCase):

    def test_packages_current_state(self):
        result = load(FakeConnection())

        self.assertEqual(result["page_key"], "packages.intro")
        self.assertEqual(result["draft_revision_id"], 9)
        self.assertEqual(result["published_revision_id"], 9)

    def test_pricing_queries_are_independent(self):
        conn = FakeConnection()
        result = load(conn, "pricing.intro")

        self.assertEqual(result["page_key"], "pricing.intro")
        self.assertEqual(len(conn.queries), 3)

        for _, params in conn.queries:
            self.assertEqual(params, ("pricing.intro",))

    def test_empty_pricing_history(self):
        conn = FakeConnection(
            state=(None, None),
            revisions=[],
            events=[],
        )
        result = load(conn, "pricing.intro")

        self.assertEqual(result["revisions"], [])
        self.assertEqual(result["events"], [])

    def test_revisions_remain_separate_from_ids(self):
        result = load(FakeConnection())
        latest = result["revisions"][0]

        self.assertEqual(latest["revision_number"], 2)
        self.assertEqual(latest["revision_id"], 9)

    def test_current_revision_status(self):
        result = load(FakeConnection())
        latest = result["revisions"][0]

        self.assertTrue(latest["is_draft"])
        self.assertTrue(latest["is_published"])
        self.assertTrue(latest["was_published"])

    def test_unpublished_test_draft_not_restorable(self):
        result = load(FakeConnection())
        older = result["revisions"][1]

        self.assertFalse(older["is_draft"])
        self.assertFalse(older["is_published"])
        self.assertFalse(older["was_published"])

    def test_previously_published_revision(self):
        events = [
            (4, 9, 6, "publish", 9, "2026-11-21"),
            (3, 6, None, "publish", 9, "2026-11-20"),
        ]
        result = load(FakeConnection(events=events))
        older = result["revisions"][1]

        self.assertTrue(older["was_published"])
        self.assertFalse(older["is_published"])

    def test_restoration_event_marks_published_history(self):
        events = [
            (5, 6, 9, "restore", 9, "2026-11-21"),
            (4, 9, 6, "publish", 9, "2026-11-21"),
            (3, 6, None, "publish", 9, "2026-11-20"),
        ]
        conn = FakeConnection(
            state=(9, 6),
            events=events,
        )
        result = load(conn)

        older = result["revisions"][1]
        self.assertTrue(older["is_published"])
        self.assertTrue(older["was_published"])
        self.assertEqual(result["events"][0]["action"], "restore")

    def test_other_sections_rejected(self):
        conn = FakeConnection()

        with self.assertRaises(MarketingCMSSectionError):
            load(conn, "home.peachweb")

        self.assertEqual(conn.queries, [])

    def test_missing_section_state_rejected(self):
        with self.assertRaises(MarketingCMSHistoryError):
            load(FakeConnection(state=None))

    def test_missing_active_draft_rejected(self):
        with self.assertRaises(MarketingCMSHistoryError):
            load(FakeConnection(state=(88, 9)))

    def test_missing_active_publication_rejected(self):
        with self.assertRaises(MarketingCMSHistoryError):
            load(FakeConnection(state=(9, 88)))

    def test_duplicate_revision_id_rejected(self):
        rows = sample_revisions()
        rows.append(
            (9, 3, content("Duplicate"), 9, "today", None)
        )

        with self.assertRaises(MarketingCMSHistoryError):
            load(FakeConnection(revisions=rows))

    def test_duplicate_revision_number_rejected(self):
        rows = sample_revisions()
        rows.append(
            (15, 2, content("Duplicate"), 9, "today", None)
        )

        with self.assertRaises(MarketingCMSHistoryError):
            load(FakeConnection(revisions=rows))

    def test_invalid_historical_content_rejected(self):
        rows = sample_revisions()
        rows[0] = (
            9, 2,
            content("<script>invalid</script>"),
            9, "today", None,
        )

        with self.assertRaises(MarketingContentError):
            load(FakeConnection(revisions=rows))

    def test_invalid_publication_action_rejected(self):
        events = [
            (4, 9, None, "delete", 9, "today")
        ]

        with self.assertRaises(MarketingCMSHistoryError):
            load(FakeConnection(events=events))

    def test_missing_event_revision_rejected(self):
        events = [
            (4, 99, None, "publish", 9, "today")
        ]

        with self.assertRaises(MarketingCMSHistoryError):
            load(FakeConnection(events=events))

    def test_missing_previous_revision_rejected(self):
        events = [
            (4, 9, 99, "publish", 9, "today")
        ]

        with self.assertRaises(MarketingCMSHistoryError):
            load(FakeConnection(events=events))

    def test_published_state_requires_audit_event(self):
        with self.assertRaises(MarketingCMSHistoryError):
            load(FakeConnection(events=[]))

    def test_duplicate_event_id_rejected(self):
        events = sample_events()
        events.append(
            (4, 9, None, "publish", 9, "today")
        )

        with self.assertRaises(MarketingCMSHistoryError):
            load(FakeConnection(events=events))

    def test_history_does_not_write_to_database(self):
        conn = FakeConnection()
        load(conn)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 0)

        for query, _ in conn.queries:
            self.assertTrue(query.startswith("select "))


if __name__ == "__main__":
    unittest.main()
