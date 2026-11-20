"""Protected independent publication for PeachWeb and PeachBook.

No Flask routes, public rendering, or database connections
are created by importing this module.
"""

from services.psp_marketing_cms_content import (
    normalize_home_peachbook_content,
    normalize_home_peachweb_content,
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


SHOWCASE_VALIDATORS = {
    "home.peachweb": normalize_home_peachweb_content,
    "home.peachbook": normalize_home_peachbook_content,
}

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


def publish_showcase_draft(
    connection,
    *,
    section_key,
    actor_id,
    expected_draft_revision_id,
    expected_published_revision_id,
):
    """Publish one exact showcase draft with an audit trail.

    Never publishes the Home Page hero or another showcase.
    Both expected revision IDs are checked under a row lock.
    """

    section = get_section_spec(section_key)

    if section.key not in SHOWCASE_VALIDATORS:
        raise MarketingCMSSectionError(
            "This publication operation supports showcases only."
        )

    validator = SHOWCASE_VALIDATORS[section.key]

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
            "Showcase publishing requires a database transaction."
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
                    "Showcase publication state is missing."
                )

            current_draft, current_published = state

            if current_published != expected_published_revision_id:
                raise MarketingCMSConflict(
                    "The published showcase has changed. Reload first."
                )

            if current_draft != expected_draft_revision_id:
                raise MarketingCMSConflict(
                    "The showcase draft has changed. Reload first."
                )

            if current_published == expected_draft_revision_id:
                raise MarketingCMSConflict(
                    "This showcase revision is already published."
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
                    "Requested showcase revision is missing."
                )

            # Revalidate the stored image and caption before
            # allowing any published-revision update.
            validator(revision[0])

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
                    "Unable to update showcase publication."
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

            event_id = int(cur.fetchone()[0])

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
