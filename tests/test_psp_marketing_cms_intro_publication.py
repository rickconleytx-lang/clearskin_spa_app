"""Isolated tests for introduction publication transactions."""

import copy
import unittest

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_intro_publication import (
    publish_intro_draft,
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
        "heading": "Launch Special",
        "paragraph": "A valid promotional paragraph.",
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

    def execute(self, sql, parameters):
        query = " ".join(sql.lower().split())
        self.conn.queries.append((query, parameters))

        if (
            query.startswith("select draft_revision_id")
            and "for update" in query
        ):
            self.result = self.conn.state

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
                else (901,)
            )

        else:
            raise AssertionError(
                "Unexpected SQL operation: " + query
            )

    def fetchone(self):
        return self.result


class FakeConnection:

    def __init__(
        self,
        *,
        state=(17, None),
        content=None,
        autocommit=False,
        update_count=1,
        fail_stage=None,
        missing_revision=False,
        missing_audit=False,
    ):
        self.state = state
        self.content = (
            copy.deepcopy(VALID)
            if content is None
            else content
        )
        self.autocommit = autocommit
        self.update_count = update_count
        self.fail_stage = fail_stage
        self.missing_revision = missing_revision
        self.missing_audit = missing_audit
        self.queries = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def publish(
    conn,
    *,
    section_key="packages.intro",
    actor_id=5,
    draft=17,
    published=None,
):
    return publish_intro_draft(
        conn,
        section_key=section_key,
        actor_id=actor_id,
        expected_draft_revision_id=draft,
        expected_published_revision_id=published,
    )


class IntroductionPublicationTests(unittest.TestCase):

    def test_first_packages_publication(self):
        conn = FakeConnection()
        result = publish(conn)

        self.assertEqual(result["page_key"], "packages.intro")
        self.assertEqual(result["revision_id"], 17)
        self.assertIsNone(result["previous_revision_id"])
        self.assertEqual(result["publication_event_id"], 901)
        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.rollbacks, 0)

    def test_first_pricing_publication(self):
        conn = FakeConnection()
        result = publish(
            conn,
            section_key="pricing.intro",
        )

        self.assertEqual(result["page_key"], "pricing.intro")
        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.queries[0][1], ("pricing.intro",))

    def test_next_publication_retains_previous_id(self):
        conn = FakeConnection(state=(17, 12))
        result = publish(conn, published=12)

        self.assertEqual(result["previous_revision_id"], 12)
        self.assertEqual(conn.queries[3][1], (
            "packages.intro", 17, 12, "publish", 5,
        ))

    def test_rejects_other_registered_sections(self):
        conn = FakeConnection()

        with self.assertRaises(MarketingCMSSectionError):
            publish(conn, section_key="home.peachweb")

        self.assertEqual(conn.queries, [])
        self.assertEqual(conn.commits, 0)

    def test_invalid_ids_rejected_before_sql(self):
        examples = (
            {"actor_id": True},
            {"actor_id": 0},
            {"actor_id": 2**63},
            {"draft": "17"},
            {"draft": -1},
            {"published": 0},
            {"published": False},
            {"published": 2**63},
        )

        for kwargs in examples:
            with self.subTest(kwargs=kwargs):
                conn = FakeConnection()

                with self.assertRaises(ValueError):
                    publish(conn, **kwargs)

                self.assertEqual(conn.queries, [])
                self.assertEqual(conn.commits, 0)

    def test_rejects_autocommit(self):
        conn = FakeConnection(autocommit=True)

        with self.assertRaises(
            MarketingCMSConfigurationError
        ):
            publish(conn)

        self.assertEqual(conn.queries, [])
        self.assertEqual(conn.commits, 0)

    def test_stale_draft_rejected(self):
        conn = FakeConnection(state=(18, None))

        with self.assertRaises(MarketingCMSConflict):
            publish(conn)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_changed_publication_rejected(self):
        conn = FakeConnection(state=(17, 12))

        with self.assertRaises(MarketingCMSConflict):
            publish(conn, published=None)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_duplicate_publication_rejected(self):
        conn = FakeConnection(state=(17, 17))

        with self.assertRaises(MarketingCMSConflict):
            publish(conn, published=17)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_missing_section_state(self):
        conn = FakeConnection(state=None)

        with self.assertRaises(MarketingCMSNotFound):
            publish(conn)

        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(conn.commits, 0)

    def test_missing_revision(self):
        conn = FakeConnection(missing_revision=True)

        with self.assertRaises(MarketingCMSNotFound):
            publish(conn)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_invalid_stored_content(self):
        conn = FakeConnection(
            content={
                "intro": {
                    "heading": "<script>bad</script>",
                    "paragraph": "Text",
                }
            }
        )

        with self.assertRaises(MarketingContentError):
            publish(conn)

        self.assertEqual(len(conn.queries), 2)
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_failed_publication_update(self):
        conn = FakeConnection(update_count=0)

        with self.assertRaises(MarketingCMSNotFound):
            publish(conn)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_failed_audit_insert(self):
        conn = FakeConnection(fail_stage="audit")

        with self.assertRaises(RuntimeError):
            publish(conn)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_missing_audit_record(self):
        conn = FakeConnection(missing_audit=True)

        with self.assertRaises(MarketingCMSNotFound):
            publish(conn)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_all_queries_scoped_to_one_section(self):
        conn = FakeConnection()
        publish(conn, section_key="pricing.intro")

        self.assertEqual(len(conn.queries), 4)

        self.assertEqual(
            conn.queries[0][1],
            ("pricing.intro",),
        )

        self.assertEqual(
            conn.queries[1][1],
            ("pricing.intro", 17),
        )

        self.assertEqual(
            conn.queries[2][1],
            (17, 5, "pricing.intro"),
        )

        self.assertEqual(
            conn.queries[3][1],
            ("pricing.intro", 17, None, "publish", 5),
        )

        self.assertIn("for update", conn.queries[0][0])
        self.assertIn(
            "where page_key = %s",
            conn.queries[2][0],
        )
        self.assertEqual(conn.commits, 1)


if __name__ == "__main__":
    unittest.main()
