"""Publish or restore approved corporate marketing subscription products.

Only explicit product sections are accepted. Callers must enforce authenticated
Master Admin access and CSRF validation; this module enforces revision integrity
and writes a publication audit event in the same database transaction.
"""

from services.psp_marketing_cms_product_content import normalize_product_content
from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
    MarketingCMSConfigurationError,
    MarketingCMSNotFound,
)

PRODUCT_KEYS = frozenset({"solo", "peachpos", "team", "collective"})


class MarketingCMSUnpublishedProductRevision(ValueError):
    """Restoring a revision that was never publicly published is forbidden."""


def _positive_id(value, label):
    if type(value) is not int or value <= 0 or value > 9223372036854775807:
        raise ValueError(f"{label} must be a positive 64-bit integer.")


def _page_key(product_key):
    if type(product_key) is not str or product_key not in PRODUCT_KEYS:
        raise ValueError("Unsupported marketing subscription product.")
    return f"product.{product_key}"


def _change_product_publication(
    connection, *, product_key, action, revision_id, actor_id,
    expected_published_revision_id,
):
    page_key = _page_key(product_key)
    _positive_id(actor_id, "Master Admin ID")
    _positive_id(revision_id, "Target product revision")
    if expected_published_revision_id is not None:
        _positive_id(expected_published_revision_id, "Expected published revision")
    if action not in ("publish", "restore"):
        raise ValueError("Unsupported product publication action.")
    if connection.autocommit:
        raise MarketingCMSConfigurationError(
            "Product publication requires a database transaction."
        )

    try:
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT draft_revision_id, published_revision_id
                FROM psp_marketing_page_state
                WHERE page_key = %s
                FOR UPDATE
                """,
                (page_key,),
            )
            state = cur.fetchone()
            if state is None:
                raise MarketingCMSNotFound("Product CMS section state is missing.")
            current_draft, current_published = state

            if current_published != expected_published_revision_id:
                raise MarketingCMSConflict(
                    "Published product changed. Reload before publishing."
                )
            if action == "publish" and current_draft != revision_id:
                raise MarketingCMSConflict(
                    "Product draft changed. Reload before publishing."
                )
            if current_published == revision_id:
                raise MarketingCMSConflict("This product revision is already published.")

            if action == "restore":
                cur.execute(
                    """
                    SELECT 1 FROM psp_marketing_publication_events
                    WHERE page_key = %s AND revision_id = %s
                      AND action IN ('publish', 'restore')
                    LIMIT 1
                    """,
                    (page_key, revision_id),
                )
                if cur.fetchone() is None:
                    raise MarketingCMSUnpublishedProductRevision(
                        "Only previously published product revisions can be restored."
                    )

            cur.execute(
                """
                SELECT content FROM psp_marketing_revisions
                WHERE page_key = %s AND revision_id = %s
                """,
                (page_key, revision_id),
            )
            revision = cur.fetchone()
            if revision is None:
                raise MarketingCMSNotFound("Requested product revision is missing.")

            # Do not activate invalid or legacy-incompatible product data.
            normalize_product_content(revision[0])

            cur.execute(
                """
                UPDATE psp_marketing_page_state
                SET published_revision_id = %s,
                    published_at = NOW(),
                    published_by = %s,
                    updated_at = NOW()
                WHERE page_key = %s
                """,
                (revision_id, actor_id, page_key),
            )
            if cur.rowcount != 1:
                raise MarketingCMSNotFound("Unable to update product publication state.")

            cur.execute(
                """
                INSERT INTO psp_marketing_publication_events (
                    page_key, revision_id, previous_revision_id,
                    action, performed_by
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING publication_event_id
                """,
                (page_key, revision_id, current_published, action, actor_id),
            )
            event_row = cur.fetchone()
            if event_row is None:
                raise MarketingCMSConfigurationError(
                    "Product publication audit confirmation is missing."
                )
            event_id = int(event_row[0])
            connection.commit()
    except Exception:
        connection.rollback()
        raise

    return {
        "page_key": page_key,
        "action": action,
        "revision_id": revision_id,
        "previous_revision_id": current_published,
        "publication_event_id": event_id,
    }


def publish_product_draft(
    connection, *, product_key, actor_id,
    expected_draft_revision_id, expected_published_revision_id,
):
    """Publish precisely the current draft of one registered product."""
    return _change_product_publication(
        connection,
        product_key=product_key,
        action="publish",
        revision_id=expected_draft_revision_id,
        actor_id=actor_id,
        expected_published_revision_id=expected_published_revision_id,
    )


def restore_product_revision(
    connection, *, product_key, actor_id, revision_id,
    expected_published_revision_id,
):
    """Restore a previously published revision of one registered product."""
    return _change_product_publication(
        connection,
        product_key=product_key,
        action="restore",
        revision_id=revision_id,
        actor_id=actor_id,
        expected_published_revision_id=expected_published_revision_id,
    )
