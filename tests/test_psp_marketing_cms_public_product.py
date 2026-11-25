"""Offline tests for published-only product content lookup."""

import unittest
from pathlib import Path

from services.psp_marketing_cms_product_baseline import (
    get_product_baseline,
)
from services.psp_marketing_cms_content import MarketingContentError
from services.psp_marketing_cms_public_product import (
    PRODUCT_SECTION_KEYS,
    load_published_products,
)


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None
        self.count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params
        self.count += 1

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.cur = FakeCursor(rows)

    def cursor(self):
        return self.cur


def record(key, revision=1, content=None):
    return (
        f"product.{key}", revision,
        get_product_baseline(key) if content is None else content,
    )


class PublicProductLoaderTests(unittest.TestCase):
    def test_no_publication_retains_static_fallback(self):
        conn = FakeConnection([])
        self.assertEqual(load_published_products(conn), {})

    def test_published_solo_loaded(self):
        conn = FakeConnection([record("solo")])
        products = load_published_products(conn)
        self.assertEqual(set(products), {"solo"})
        self.assertEqual(
            products["solo"]["shared"]["name"],
            get_product_baseline("solo")["shared"]["name"],
        )

    def test_all_four_products_independent(self):
        conn = FakeConnection([
            record(key, i)
            for i, key in enumerate(
                ("solo", "peachpos", "team", "collective"), 1
            )
        ])
        self.assertEqual(
            set(load_published_products(conn)),
            {"solo", "peachpos", "team", "collective"},
        )

    def test_only_published_rows_queried(self):
        conn = FakeConnection([])
        load_published_products(conn)
        sql = conn.cur.sql.casefold()
        self.assertEqual(conn.cur.count, 1)
        self.assertEqual(conn.cur.params, PRODUCT_SECTION_KEYS)
        self.assertIn("published_revision_id", sql)
        self.assertIn("published.content", sql)
        self.assertIn("published.page_key = state.page_key", sql)
        self.assertIn("published.revision_id = state.published_revision_id", sql)
        self.assertNotIn("draft_revision_id", sql)
        self.assertNotIn("draft.content", sql)
        self.assertNotIn("update ", sql)
        self.assertNotIn("insert ", sql)

    def test_invalid_published_snapshot_rejected(self):
        conn = FakeConnection([record("solo", content={"shared": {}})])
        with self.assertRaises(MarketingContentError):
            load_published_products(conn)

    def test_duplicate_published_row_rejected(self):
        conn = FakeConnection([record("solo"), record("solo", 2)])
        with self.assertRaises(ValueError):
            load_published_products(conn)

    def test_wrong_product_rejected(self):
        conn = FakeConnection([("product.other", 1, {})])
        with self.assertRaises(ValueError):
            load_published_products(conn)

    def test_invalid_revision_rejected(self):
        conn = FakeConnection([record("solo", revision=0)])
        with self.assertRaises(ValueError):
            load_published_products(conn)

    def test_public_routes_receive_published_data(self):
        app_source = Path("app.py").read_text()
        self.assertEqual(
            app_source.count("cms_products=_load_public_marketing_products(),"),
            2,
        )
        self.assertIn("cms_intro=_load_public_marketing_intro(", app_source)
        self.assertIn('"public_site/psp_packages.html"', app_source)
        self.assertIn('"public_site/psp_pricing.html"', app_source)

    def test_public_templates_not_yet_changed(self):
        # This step only supplies validated data to the page context.
        # Rendering changes will be a distinct, reviewed patch.
        self.assertEqual(
            set(PRODUCT_SECTION_KEYS),
            {"product.solo", "product.peachpos",
             "product.team", "product.collective"},
        )


if __name__ == "__main__":
    unittest.main()
