"""Read only approved, published corporate product content.

This module never reads marketing drafts and never falls back to
unpublished content. An empty result means retain existing static cards.
"""

from services.psp_marketing_cms_product_content import (
    normalize_product_content,
)

PRODUCT_KEYS = ("solo", "peachpos", "team", "collective")
PRODUCT_SECTION_KEYS = tuple(
    f"product.{key}" for key in PRODUCT_KEYS
)


def load_published_products(connection):
    """Return validated published product snapshots keyed by product slug.

    The caller is responsible for transaction cleanup and connection close.
    There is no database connection creation or mutation here.
    """
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT state.page_key,
                   state.published_revision_id,
                   published.content
            FROM psp_marketing_page_state AS state
            JOIN psp_marketing_revisions AS published
              ON published.page_key = state.page_key
             AND published.revision_id = state.published_revision_id
            WHERE state.page_key IN (%s, %s, %s, %s)
              AND state.published_revision_id IS NOT NULL
            ORDER BY state.page_key
            """,
            PRODUCT_SECTION_KEYS,
        )
        rows = cur.fetchall()

    products = {}
    for row in rows:
        if len(row) != 3:
            raise ValueError("Invalid published product row")
        section_key, revision_id, content = row
        if section_key not in PRODUCT_SECTION_KEYS:
            raise ValueError("Unregistered product publication")
        if type(revision_id) is not int or revision_id <= 0:
            raise ValueError("Invalid published product revision")
        product_key = section_key.partition(".")[2]
        if product_key in products:
            raise ValueError("Duplicate published product row")
        products[product_key] = normalize_product_content(content)

    return products
