"""Isolated transaction tests for introduction restoration."""

import copy
import unittest

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_intro_publication import (
    restore_intro_revision,
)
from services.psp_marketing_cms_publication import (
    MarketingCMSUnpublishedRevision,
)
from services.psp_marketing_cms_sections import (
    MarketingCMSSectionError,
)
from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
    MarketingCMSConfigurationError,
    MarketingCMSNotFound,
)


VALID = {
    "intro": {
        "heading": "Previous promotion",
        "paragraph": "Previously published introduction.",
    }
}


class FakeCursor:

    def __init__(self, connection):
        self.conn = connection
        self.rowcount = 0
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

        elif query.startswith(
            "select 1 from psp_marketing_publication_events"
        ):
            self.result = (
                (1,) if self.conn.was_published else None
            )

        elif query.startswith(
            "select content from psp_marketing_revisions"
        ):
            self.result = (
                None
                if self.conn.missing_revision
                else (self.conn.content,)
            )

        elif query.startswith(
            "update psp_marketing_page_state"
        ):
            if self.conn.fail_stage == "update":
                raise RuntimeError("Simulated update failure")

            self.rowcount = self.conn.update_count

        elif query.startswith(
            "insert into psp_marketing_publication_events"
        ):
            if self.conn.fail_stage == "audit":
                raise RuntimeError("Simulated audit failure")

            self.result = (
                None
                if self.conn.missing_audit
                else (44,)
            )

        else:
            raise AssertionError(
                "Unexpected SQL: " + query
            )

    def fetchone(self):
        return self.result


class FakeConnection:

    def __init__(
        self,
        *,
        state=(11, 9),
        content=None,
        was_published=True,
        autocommit=False,
        update_count=1,
        missing_revision=False,
        missing_audit=False,
        fail_stage=None,
    ):
        self.state = state
        self.content = (
            copy.deepcopy(VALID)
            if content is None
            else content
        )
        self.was_published = was_published
        self.autocommit = autocommit
        self.update_count = update_count
        self.missing_revision = missing_revision
        self.missing_audit = missing_audit
        self.fail_stage = fail_stage
        self.queries = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def restore(
    conn,
    *,
    section_key="packages.intro",
    actor_id=5,
    revision_id=7,
    expected_published_revision_id=9,
):
    return restore_intro_revision(
        conn,
        section_key=section_key,
        actor_id=actor_id,
        revision_id=revision_id,
        expected_published_revision_id=(
            expected_published_revision_id
        ),
    )


class IntroductionRestoreTests(unittest.TestCase):

    def test_packages_restoration(self):
        conn = FakeConnection()
        result = restore(conn)

        self.assertEqual(result["page_key"], "packages.intro")
        self.assertEqual(result["revision_id"], 7)
        self.assertEqual(result["previous_revision_id"], 9)
        self.assertEqual(result["action"], "restore")
        self.assertEqual(result["publication_event_id"], 44)
        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.rollbacks, 0)

    def test_pricing_restoration(self):
        conn = FakeConnection()
        result = restore(
            conn,
            section_key="pricing.intro",
        )

        self.assertEqual(result["page_key"], "pricing.intro")
        self.assertEqual(conn.queries[0][1], ("pricing.intro",))
        self.assertEqual(conn.commits, 1)

    def test_audit_records_previous_revision(self):
        conn = FakeConnection()
        restore(conn)

        self.assertEqual(
            conn.queries[4][1],
            ("packages.intro", 7, 9, "restore", 5),
        )

    def test_never_published_revision_rejected(self):
        conn = FakeConnection(was_published=False)

        with self.assertRaises(
            MarketingCMSUnpublishedRevision
        ):
            restore(conn)

        self.assertEqual(len(conn.queries), 2)
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_already_published_revision_rejected(self):
        conn = FakeConnection(state=(11, 7))

        with self.assertRaises(MarketingCMSConflict):
            restore(
                conn,
                expected_published_revision_id=7,
            )

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_stale_publication_rejected(self):
        conn = FakeConnection(state=(11, 10))

        with self.assertRaises(MarketingCMSConflict):
            restore(conn)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_missing_section_state_rejected(self):
        conn = FakeConnection(state=None)

        with self.assertRaises(MarketingCMSNotFound):
            restore(conn)

        self.assertEqual(conn.rollbacks, 1)

    def test_missing_target_revision_rejected(self):
        conn = FakeConnection(missing_revision=True)

        with self.assertRaises(MarketingCMSNotFound):
            restore(conn)

        self.assertEqual(conn.rollbacks, 1)

    def test_invalid_stored_content_rejected(self):
        conn = FakeConnection(
            content={
                "intro": {
                    "heading": "<script>invalid</script>",
                    "paragraph": "Text",
                }
            }
        )

        with self.assertRaises(MarketingContentError):
            restore(conn)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(len(conn.queries), 3)

    def test_failed_update_rejected(self):
        conn = FakeConnection(update_count=0)

        with self.assertRaises(MarketingCMSNotFound):
            restore(conn)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_update_exception_rolls_back(self):
        conn = FakeConnection(fail_stage="update")

        with self.assertRaises(RuntimeError):
            restore(conn)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_audit_exception_rolls_back(self):
        conn = FakeConnection(fail_stage="audit")

        with self.assertRaises(RuntimeError):
            restore(conn)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_missing_audit_result_rejected(self):
        conn = FakeConnection(missing_audit=True)

        with self.assertRaises(MarketingCMSNotFound):
            restore(conn)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_other_sections_rejected(self):
        conn = FakeConnection()

        with self.assertRaises(MarketingCMSSectionError):
            restore(
                conn,
                section_key="home.peachweb",
            )

        self.assertEqual(conn.queries, [])

    def test_invalid_ids_rejected_before_sql(self):
        examples = (
            {"actor_id": True},
            {"actor_id": 0},
            {"actor_id": 2**63},
            {"revision_id": "7"},
            {"revision_id": 0},
            {"revision_id": False},
            {"expected_published_revision_id": None},
            {"expected_published_revision_id": 0},
            {"expected_published_revision_id": 2**63},
        )

        for kwargs in examples:
            with self.subTest(kwargs=kwargs):
                conn = FakeConnection()

                with self.assertRaises(ValueError):
                    restore(conn, **kwargs)

                self.assertEqual(conn.queries, [])
                self.assertEqual(conn.commits, 0)

    def test_autocommit_rejected(self):
        conn = FakeConnection(autocommit=True)

        with self.assertRaises(
            MarketingCMSConfigurationError
        ):
            restore(conn)

        self.assertEqual(conn.queries, [])
        self.assertEqual(conn.commits, 0)

    def test_row_lock_scope_and_preserved_draft(self):
        conn = FakeConnection(state=(11, 9))
        restore(conn)

        self.assertEqual(len(conn.queries), 5)
        self.assertIn("for update", conn.queries[0][0])

        self.assertEqual(
            conn.queries[0][1],
            ("packages.intro",),
        )

        self.assertEqual(
            conn.queries[1][1],
            ("packages.intro", 7),
        )

        self.assertEqual(
            conn.queries[2][1],
            ("packages.intro", 7),
        )

        self.assertEqual(
            conn.queries[3][1],
            (7, 5, "packages.intro"),
        )

        update_sql = conn.queries[3][0]

        self.assertNotIn(
            "set draft_revision_id",
            update_sql,
        )
        self.assertIn(
            "set published_revision_id",
            update_sql,
        )


if __name__ == "__main__":
    unittest.main()
