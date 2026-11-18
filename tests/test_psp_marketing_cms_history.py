import unittest
from datetime import datetime, timezone

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_history import (
    MarketingCMSHistoryError,
    load_home_history,
)


WHEN = datetime(
    2026, 11, 18, 5, 0, tzinfo=timezone.utc
)


def content(text="First Revision"):
    return {
        "hero": {
            "primary_button_text": text,
            "secondary_button_text": "View Pricing",
            "pricing_sentence": (
                "Solo is $49/month or $490/year "
                "after the 10-day free trial."
            ),
        },
    }


def revision(rid, number, text):
    return (
        rid, number, content(text), 7, WHEN, None
    )


def event(eid, rid, previous=None, action="publish"):
    return (eid, rid, previous, action, 7, WHEN)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.current = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        assert sql.lstrip().upper().startswith("SELECT")
        assert params == ("home",)

        if "FROM psp_marketing_page_state" in sql:
            self.current = "state"
        elif "FROM psp_marketing_revisions" in sql:
            self.current = "revisions"
        elif "FROM psp_marketing_publication_events" in sql:
            self.current = "events"
        else:
            raise AssertionError("Unexpected SQL")

        self.connection.queries.append(sql)

    def fetchone(self):
        assert self.current == "state"
        return self.connection.state

    def fetchall(self):
        if self.current == "revisions":
            return list(self.connection.revisions)

        if self.current == "events":
            return list(self.connection.events)

        raise AssertionError("Unexpected fetchall")


class FakeConnection:
    def __init__(
        self,
        state=(1, 1),
        revisions=None,
        events=None,
    ):
        self.state = state
        self.revisions = (
            [revision(1, 1, "First Revision")]
            if revisions is None
            else revisions
        )
        self.events = (
            [event(1, 1)]
            if events is None
            else events
        )
        self.queries = []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        raise AssertionError(
            "History must never commit."
        )

    def rollback(self):
        raise AssertionError(
            "History service must not manage transactions."
        )


class MarketingCMSHistoryTests(unittest.TestCase):

    def test_current_published_revision(self):
        conn = FakeConnection()
        history = load_home_history(conn)

        self.assertEqual(history["draft_revision_id"], 1)
        self.assertEqual(history["published_revision_id"], 1)
        self.assertEqual(len(history["revisions"]), 1)
        self.assertTrue(
            history["revisions"][0]["is_published"]
        )
        self.assertTrue(
            history["revisions"][0]["was_published"]
        )
        self.assertEqual(len(conn.queries), 3)

    def test_newer_draft_is_not_published(self):
        conn = FakeConnection(
            state=(2, 1),
            revisions=[
                revision(2, 2, "New Draft"),
                revision(1, 1, "First Revision"),
            ],
            events=[event(1, 1)],
        )

        history = load_home_history(conn)
        latest, previous = history["revisions"]

        self.assertTrue(latest["is_draft"])
        self.assertFalse(latest["is_published"])
        self.assertFalse(latest["was_published"])

        self.assertTrue(previous["is_published"])
        self.assertTrue(previous["was_published"])

    def test_restored_revision_has_history(self):
        conn = FakeConnection(
            state=(2, 1),
            revisions=[
                revision(2, 2, "Second Version"),
                revision(1, 1, "Original Version"),
            ],
            events=[
                event(3, 1, 2, "restore"),
                event(2, 2, 1, "publish"),
                event(1, 1),
            ],
        )

        history = load_home_history(conn)

        self.assertEqual(
            [e["action"] for e in history["events"]],
            ["restore", "publish", "publish"],
        )
        self.assertTrue(
            all(r["was_published"] for r in history["revisions"])
        )
        self.assertEqual(history["published_revision_id"], 1)
        self.assertEqual(history["draft_revision_id"], 2)

    def test_empty_page_history_is_valid(self):
        conn = FakeConnection(
            state=(None, None),
            revisions=[],
            events=[],
        )

        history = load_home_history(conn)

        self.assertEqual(history["revisions"], [])
        self.assertEqual(history["events"], [])
        self.assertIsNone(history["published_revision_id"])

    def test_missing_page_state_is_rejected(self):
        conn = FakeConnection(state=None)

        with self.assertRaises(MarketingCMSHistoryError):
            load_home_history(conn)

    def test_missing_active_draft_is_rejected(self):
        conn = FakeConnection(state=(99, 1))

        with self.assertRaises(MarketingCMSHistoryError):
            load_home_history(conn)

    def test_missing_active_publication_is_rejected(self):
        conn = FakeConnection(state=(1, 99))

        with self.assertRaises(MarketingCMSHistoryError):
            load_home_history(conn)

    def test_event_with_missing_revision_is_rejected(self):
        conn = FakeConnection(
            events=[event(1, 99)],
        )

        with self.assertRaises(MarketingCMSHistoryError):
            load_home_history(conn)

    def test_unknown_publication_action_is_rejected(self):
        conn = FakeConnection(
            events=[event(1, 1, action="delete")],
        )

        with self.assertRaises(MarketingCMSHistoryError):
            load_home_history(conn)

    def test_invalid_historical_content_is_rejected(self):
        invalid = (
            1, 1, {"hero": {}}, 7, WHEN, None
        )

        conn = FakeConnection(revisions=[invalid])

        with self.assertRaises(MarketingContentError):
            load_home_history(conn)


if __name__ == "__main__":
    unittest.main()
