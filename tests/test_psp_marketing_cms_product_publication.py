"""Isolated, database-free transactional product CMS publication tests."""

import unittest
from unittest.mock import patch

from services.psp_marketing_cms_product_publication import (
    MarketingCMSUnpublishedProductRevision,
    publish_product_draft,
    restore_product_revision,
)
from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
    MarketingCMSConfigurationError,
    MarketingCMSNotFound,
)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = -1
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        statement = " ".join(query.split()).lower()
        self.connection.queries.append((statement, params))
        self.rowcount = -1
        self.result = None
        conn = self.connection

        if statement.startswith("select draft_revision_id, published_revision_id"):
            if params[0] == conn.page_key:
                self.result = (conn.draft, conn.published)
        elif statement.startswith("select 1 from psp_marketing_publication_events"):
            if (params[0], params[1]) in conn.history:
                self.result = (1,)
        elif statement.startswith("select content from psp_marketing_revisions"):
            if (params[0], params[1]) in conn.revisions:
                self.result = (conn.revisions[(params[0], params[1])],)
        elif statement.startswith("update psp_marketing_page_state"):
            if conn.fail_update:
                self.rowcount = 0
            else:
                self.rowcount = 1
                conn.pending = (params[2], params[0])
        elif statement.startswith("insert into psp_marketing_publication_events"):
            if conn.fail_audit:
                raise RuntimeError("Audit insert failed")
            conn.pending_event = params
            self.result = (99,)
        else:
            raise AssertionError(f"Unexpected SQL: {statement}")

    def fetchone(self):
        return self.result


class FakeConnection:
    def __init__(self, *, product="solo", draft=11, published=None):
        self.autocommit = False
        self.page_key = f"product.{product}"
        self.draft = draft
        self.published = published
        self.revisions = {
            (self.page_key, 11): {"example": "draft"},
            (self.page_key, 9): {"example": "previous"},
        }
        self.history = set()
        self.queries = []
        self.pending = None
        self.pending_event = None
        self.fail_update = False
        self.fail_audit = False
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1
        if self.pending is not None:
            self.published = self.pending[1]
        if self.pending_event is not None:
            self.history.add((self.pending_event[0], self.pending_event[1]))
        self.pending = None
        self.pending_event = None

    def rollback(self):
        self.rollbacks += 1
        self.pending = None
        self.pending_event = None


class ProductPublicationTests(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConnection()
        self.validation_patch = patch(
            "services.psp_marketing_cms_product_publication.normalize_product_content"
        )
        self.validate = self.validation_patch.start()
        self.addCleanup(self.validation_patch.stop)

    def publish(self, **overrides):
        data = {
            "product_key": "solo", "actor_id": 7,
            "expected_draft_revision_id": 11,
            "expected_published_revision_id": None,
        }
        data.update(overrides)
        return publish_product_draft(self.conn, **data)

    def restore(self, **overrides):
        data = {
            "product_key": "solo", "actor_id": 7,
            "revision_id": 9,
            "expected_published_revision_id": 11,
        }
        data.update(overrides)
        return restore_product_revision(self.conn, **data)

    def test_first_publish_and_audit(self):
        outcome = self.publish()
        self.assertEqual(outcome["page_key"], "product.solo")
        self.assertEqual(outcome["revision_id"], 11)
        self.assertIsNone(outcome["previous_revision_id"])
        self.assertEqual(outcome["publication_event_id"], 99)
        self.assertEqual(self.conn.commits, 1)
        self.assertEqual(self.conn.published, 11)
        self.validate.assert_called_once_with({"example": "draft"})
        self.assertIn(("product.solo", 11), self.conn.history)
        self.assertIn("for update", self.conn.queries[0][0])

    def test_subsequent_publication(self):
        self.conn.published = 9
        result = self.publish(expected_published_revision_id=9)
        self.assertEqual(result["previous_revision_id"], 9)
        self.assertEqual(self.conn.published, 11)

    def test_restore_published_revision(self):
        self.conn.published = 11
        self.conn.history.add(("product.solo", 9))
        result = self.restore()
        self.assertEqual(result["action"], "restore")
        self.assertEqual(self.conn.published, 9)
        self.assertIn(("product.solo", 9), self.conn.history)

    def test_restore_unpublished_revision_rejected(self):
        self.conn.published = 11
        with self.assertRaises(MarketingCMSUnpublishedProductRevision):
            self.restore()
        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_stale_draft_rejected(self):
        self.conn.draft = 12
        with self.assertRaises(MarketingCMSConflict):
            self.publish()
        self.assertEqual(self.conn.commits, 0)

    def test_stale_published_revision_rejected(self):
        self.conn.published = 9
        with self.assertRaises(MarketingCMSConflict):
            self.publish()
        self.assertEqual(self.conn.commits, 0)

    def test_duplicate_publication_rejected(self):
        self.conn.published = 11
        with self.assertRaises(MarketingCMSConflict):
            self.publish(expected_published_revision_id=11)

    def test_no_draft_rejected(self):
        self.conn.draft = None
        with self.assertRaises(ValueError):
            self.publish(expected_draft_revision_id=None)
        self.assertFalse(self.conn.queries)

    def test_missing_state_rejected(self):
        with self.assertRaises(MarketingCMSNotFound):
            self.publish(product_key="team")
        self.assertEqual(self.conn.rollbacks, 1)

    def test_missing_revision_rejected(self):
        del self.conn.revisions[("product.solo", 11)]
        with self.assertRaises(MarketingCMSNotFound):
            self.publish()
        self.assertEqual(self.conn.rollbacks, 1)

    def test_invalid_content_rolls_back(self):
        self.validate.side_effect = ValueError("Invalid stored product snapshot")
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_failed_update_rolls_back(self):
        self.conn.fail_update = True
        with self.assertRaises(MarketingCMSNotFound):
            self.publish()
        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_failed_audit_rolls_back(self):
        self.conn.fail_audit = True
        with self.assertRaises(RuntimeError):
            self.publish()
        self.assertEqual(self.conn.commits, 0)
        self.assertIsNone(self.conn.pending)
        self.assertEqual(self.conn.rollbacks, 1)

    def test_rejects_autocommit(self):
        self.conn.autocommit = True
        with self.assertRaises(MarketingCMSConfigurationError):
            self.publish()
        self.assertFalse(self.conn.queries)

    def test_rejects_unregistered_product_before_sql(self):
        for key in ("home", "product.solo", "unknown", "", None):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.publish(product_key=key)
        self.assertFalse(self.conn.queries)

    def test_rejects_invalid_actor_and_revision_before_sql(self):
        for actor in (True, 0, -1, "7", None, 2**63):
            with self.subTest(actor=actor):
                with self.assertRaises(ValueError):
                    self.publish(actor_id=actor)
        for revision in (False, 0, "11", 2**63):
            with self.subTest(revision=revision):
                with self.assertRaises(ValueError):
                    self.publish(expected_draft_revision_id=revision)
        self.assertFalse(self.conn.queries)

    def test_rejects_invalid_published_revision_before_sql(self):
        with self.assertRaises(ValueError):
            self.publish(expected_published_revision_id="11")
        self.assertFalse(self.conn.queries)

    def test_restore_revision_scoped_to_same_product(self):
        self.conn.published = 11
        self.conn.history.add(("product.team", 9))
        with self.assertRaises(MarketingCMSUnpublishedProductRevision):
            self.restore()
        statements = [sql for sql, _ in self.conn.queries]
        self.assertTrue(any("publication_events" in sql for sql in statements))
        self.assertEqual(self.conn.commits, 0)


if __name__ == "__main__":
    unittest.main()
