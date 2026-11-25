"""Transactional publication of Packages/Pricing introductions.

No Flask routes, database connections, or public rendering.
Only two explicitly registered introduction sections are supported.
"""

from services.psp_marketing_cms_page_intro import (
    INTRO_SECTION_KEYS,
    normalize_page_intro_content,
)
from services.psp_marketing_cms_sections import (
    MarketingCMSSectionError,
    get_section_spec,
)
from services.psp_marketing_cms_service import (
    MarketingCMSConflict,
    MarketingCMSConfigurationError,
    MarketingCMSNotFound,
)


MAX_DATABASE_ID = 9223372036854775807


def _require_id(value, label, *, optional=False):
    if optional and value is None:
        return

    if (
        type(value) is not int
        or value <= 0
        or value > MAX_DATABASE_ID
    ):
        raise ValueError(f"Invalid {label}.")


def publish_intro_draft(
    connection,
    *,
    section_key,
    actor_id,
    expected_draft_revision_id,
    expected_published_revision_id,
):
    """Publish precisely one current introduction draft.

    Verify both revision IDs under a row lock.
    Revalidate stored content and write the publication audit
    in the same transaction. Never alter the current draft.
    """
    section = get_section_spec(section_key)

    if section.key not in INTRO_SECTION_KEYS:
        raise MarketingCMSSectionError(
            "Publication supports page introductions only."
        )

    _require_id(actor_id, "Master Admin ID")
    _require_id(
        expected_draft_revision_id,
        "expected draft revision",
    )
    _require_id(
        expected_published_revision_id,
        "expected published revision",
        optional=True,
    )

    if connection.autocommit:
        raise MarketingCMSConfigurationError(
            "Introduction publishing requires a transaction."
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
                (section.key,),
            )

            state = cur.fetchone()

            if state is None:
                raise MarketingCMSNotFound(
                    "Introduction publication state is missing."
                )

            current_draft, current_published = state

            if current_published != expected_published_revision_id:
                raise MarketingCMSConflict(
                    "The published introduction has changed. "
                    "Reload before publishing."
                )

            if current_draft != expected_draft_revision_id:
                raise MarketingCMSConflict(
                    "The introduction draft has changed. "
                    "Reload before publishing."
                )

            if current_published == expected_draft_revision_id:
                raise MarketingCMSConflict(
                    "This introduction revision is already published."
                )

            cur.execute(
                """
                SELECT content
                FROM psp_marketing_revisions
                WHERE page_key = %s
                  AND revision_id = %s
                """,
                (
                    section.key,
                    expected_draft_revision_id,
                ),
            )

            revision = cur.fetchone()

            if revision is None:
                raise MarketingCMSNotFound(
                    "Requested introduction revision is missing."
                )

            # Never publish invalid or unrecognized stored content.
            normalize_page_intro_content(
                section.key,
                revision[0],
            )

            cur.execute(
                """
                UPDATE psp_marketing_page_state
                SET published_revision_id = %s,
                    published_at = NOW(),
                    published_by = %s,
                    updated_at = NOW()
                WHERE page_key = %s
                """,
                (
                    expected_draft_revision_id,
                    actor_id,
                    section.key,
                ),
            )

            if cur.rowcount != 1:
                raise MarketingCMSNotFound(
                    "Unable to update introduction publication."
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
                    section.key,
                    expected_draft_revision_id,
                    current_published,
                    "publish",
                    actor_id,
                ),
            )

            event = cur.fetchone()

            if event is None:
                raise MarketingCMSNotFound(
                    "Introduction publication audit was not created."
                )

            event_id = int(event[0])

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    return {
        "page_key": section.key,
        "action": "publish",
        "revision_id": expected_draft_revision_id,
        "previous_revision_id": current_published,
        "publication_event_id": event_id,
    }


def restore_intro_revision(
    connection,
    *,
    section_key,
    actor_id,
    revision_id,
    expected_published_revision_id,
):
    """Restore a previously published introduction revision.

    Only Packages and Pricing introductions are supported.
    The current draft is preserved. Publication and audit
    changes occur together in a single transaction.
    """
    from services.psp_marketing_cms_publication import (
        MarketingCMSUnpublishedRevision,
    )

    section = get_section_spec(section_key)

    if section.key not in INTRO_SECTION_KEYS:
        raise MarketingCMSSectionError(
            "Restoration supports page introductions only."
        )

    _require_id(actor_id, "Master Admin ID")
    _require_id(revision_id, "target revision")
    _require_id(
        expected_published_revision_id,
        "expected published revision",
    )

    if connection.autocommit:
        raise MarketingCMSConfigurationError(
            "Introduction restoration requires a transaction."
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
                (section.key,),
            )

            state = cur.fetchone()

            if state is None:
                raise MarketingCMSNotFound(
                    "Introduction publication state is missing."
                )

            current_draft, current_published = state

            if current_published != expected_published_revision_id:
                raise MarketingCMSConflict(
                    "The published introduction has changed. "
                    "Reload before restoring."
                )

            if current_published == revision_id:
                raise MarketingCMSConflict(
                    "This introduction revision is already published."
                )

            # A saved draft is not automatically eligible
            # for restoration. It must have been published
            # at least once before.
            cur.execute(
                """
                SELECT 1
                FROM psp_marketing_publication_events
                WHERE page_key = %s
                  AND revision_id = %s
                  AND action IN ('publish', 'restore')
                LIMIT 1
                """,
                (section.key, revision_id),
            )

            if cur.fetchone() is None:
                raise MarketingCMSUnpublishedRevision(
                    "Only previously published introduction "
                    "revisions can be restored."
                )

            cur.execute(
                """
                SELECT content
                FROM psp_marketing_revisions
                WHERE page_key = %s
                  AND revision_id = %s
                """,
                (section.key, revision_id),
            )

            revision = cur.fetchone()

            if revision is None:
                raise MarketingCMSNotFound(
                    "Requested introduction revision is missing."
                )

            normalize_page_intro_content(
                section.key,
                revision[0],
            )

            cur.execute(
                """
                UPDATE psp_marketing_page_state
                SET published_revision_id = %s,
                    published_at = NOW(),
                    published_by = %s,
                    updated_at = NOW()
                WHERE page_key = %s
                """,
                (revision_id, actor_id, section.key),
            )

            if cur.rowcount != 1:
                raise MarketingCMSNotFound(
                    "Unable to update introduction publication."
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
                    section.key,
                    revision_id,
                    current_published,
                    "restore",
                    actor_id,
                ),
            )

            event = cur.fetchone()

            if event is None:
                raise MarketingCMSNotFound(
                    "Introduction restoration audit was not created."
                )

            event_id = int(event[0])

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    return {
        "page_key": section.key,
        "action": "restore",
        "revision_id": revision_id,
        "previous_revision_id": current_published,
        "publication_event_id": event_id,
    }
