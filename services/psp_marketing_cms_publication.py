"""Publish and restore corporate marketing Home Page revisions.

Calling Flask routes must independently enforce authenticated
Master Admin authorization and CSRF protection.

Use a dedicated database connection with autocommit disabled.
This module does not connect to the database on its own.
"""

from services.psp_marketing_cms_content import (
    normalize_home_content,
)
from services.psp_marketing_cms_service import (
    HOME_PAGE_KEY,
    MarketingCMSConflict,
    MarketingCMSConfigurationError,
    MarketingCMSNotFound,
)


class MarketingCMSUnpublishedRevision(ValueError):
    """A revision has never been published."""


def _require_positive_id(value, label):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise ValueError(f"{label} must be a positive integer.")


def _check_optional_revision(value):
    if value is not None:
        _require_positive_id(
            value, "Expected published revision"
        )


def _change_publication(
    connection,
    *,
    action,
    revision_id,
    actor_id,
    expected_published_revision_id,
):
    _require_positive_id(actor_id, "Master Admin ID")
    _require_positive_id(revision_id, "Target revision")
    _check_optional_revision(expected_published_revision_id)

    if action not in ("publish", "restore"):
        raise ValueError("Unsupported publication action.")

    if connection.autocommit:
        raise MarketingCMSConfigurationError(
            "Publishing requires a database transaction."
        )

    try:
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    draft_revision_id,
                    published_revision_id
                FROM psp_marketing_page_state
                WHERE page_key = %s
                FOR UPDATE
                """,
                (HOME_PAGE_KEY,),
            )
            row = cur.fetchone()

            if row is None:
                raise MarketingCMSNotFound(
                    "Marketing Home Page state is missing."
                )

            current_draft, current_published = row

            if (
                current_published
                != expected_published_revision_id
            ):
                raise MarketingCMSConflict(
                    "Published content has changed. Reload first."
                )

            if action == "publish" and current_draft != revision_id:
                raise MarketingCMSConflict(
                    "Draft has changed. Reload before publishing."
                )

            if current_published == revision_id:
                raise MarketingCMSConflict(
                    "This revision is already published."
                )

            if action == "restore":
                cur.execute(
                    """
                    SELECT 1
                    FROM psp_marketing_publication_events
                    WHERE page_key = %s
                      AND revision_id = %s
                      AND action IN ('publish', 'restore')
                    LIMIT 1
                    """,
                    (HOME_PAGE_KEY, revision_id),
                )

                if cur.fetchone() is None:
                    raise MarketingCMSUnpublishedRevision(
                        "Only previously published revisions "
                        "can be restored."
                    )

            cur.execute(
                """
                SELECT content
                FROM psp_marketing_revisions
                WHERE page_key = %s
                  AND revision_id = %s
                """,
                (HOME_PAGE_KEY, revision_id),
            )
            revision_row = cur.fetchone()

            if revision_row is None:
                raise MarketingCMSNotFound(
                    "Requested marketing revision is missing."
                )

            # Validate historical content before activation.
            normalize_home_content(revision_row[0])

            cur.execute(
                """
                UPDATE psp_marketing_page_state
                SET published_revision_id = %s,
                    published_at = NOW(),
                    published_by = %s,
                    updated_at = NOW()
                WHERE page_key = %s
                """,
                (revision_id, actor_id, HOME_PAGE_KEY),
            )

            if cur.rowcount != 1:
                raise MarketingCMSNotFound(
                    "Unable to update publication state."
                )

            cur.execute(
                """
                INSERT INTO psp_marketing_publication_events (
                    page_key,
                    revision_id,
                    previous_revision_id,
                    action,
                    performed_by
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING publication_event_id
                """,
                (
                    HOME_PAGE_KEY,
                    revision_id,
                    current_published,
                    action,
                    actor_id,
                ),
            )

            event_id = int(cur.fetchone()[0])

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    return {
        "page_key": HOME_PAGE_KEY,
        "action": action,
        "revision_id": revision_id,
        "previous_revision_id": current_published,
        "publication_event_id": event_id,
    }


def publish_home_draft(
    connection,
    *,
    actor_id,
    expected_draft_revision_id,
    expected_published_revision_id,
):
    """Publish precisely the current approved draft."""

    _require_positive_id(
        expected_draft_revision_id,
        "Expected draft revision",
    )

    return _change_publication(
        connection,
        action="publish",
        revision_id=expected_draft_revision_id,
        actor_id=actor_id,
        expected_published_revision_id=(
            expected_published_revision_id
        ),
    )


def restore_home_revision(
    connection,
    *,
    actor_id,
    revision_id,
    expected_published_revision_id,
):
    """Restore a revision with existing publication history.

    The current draft is preserved, and a new restore audit
    event records the previously active revision.
    """

    return _change_publication(
        connection,
        action="restore",
        revision_id=revision_id,
        actor_id=actor_id,
        expected_published_revision_id=(
            expected_published_revision_id
        ),
    )
