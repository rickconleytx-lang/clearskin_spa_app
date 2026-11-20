"""Corporate marketing CMS database operations.

This module implements Home Page draft storage only.

The calling Flask route must enforce authenticated Master Admin
access and supply the authenticated user ID from the session.

No method in this module publishes website content.
"""

from psycopg2.extras import Json

from services.psp_marketing_cms_content import (
    normalize_home_content,
    normalize_home_promotion_content,
    normalize_home_peachweb_content,
    normalize_home_peachbook_content,
)
from services.psp_marketing_cms_sections import (
    MarketingCMSSectionError,
    get_section_spec,
)

HOME_PAGE_KEY = "home"


class MarketingCMSConflict(RuntimeError):
    """A newer draft exists; refresh before editing."""


class MarketingCMSNotFound(LookupError):
    """The CMS page state has not been initialized."""


class MarketingCMSConfigurationError(RuntimeError):
    """A safe transaction cannot be guaranteed."""


def _check_actor_id(actor_id):
    if (
        isinstance(actor_id, bool)
        or not isinstance(actor_id, int)
        or actor_id <= 0
    ):
        raise ValueError(
            "A valid authenticated Master Admin ID is required."
        )


def _check_expected_revision(revision_id):
    if revision_id is None:
        return

    if (
        isinstance(revision_id, bool)
        or not isinstance(revision_id, int)
        or revision_id <= 0
    ):
        raise ValueError(
            "Expected draft revision ID is invalid."
        )


def load_section_state(connection, *, section_key):
    """Read draft and published revisions for a registered section.

    A missing draft or published revision returns None.
    This method never changes publication state.
    """

    section = get_section_spec(section_key)

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT
                state.draft_revision_id,
                draft.content,
                state.published_revision_id,
                published.content
            FROM psp_marketing_page_state AS state
            LEFT JOIN psp_marketing_revisions AS draft
              ON draft.page_key = state.page_key
             AND draft.revision_id = state.draft_revision_id
            LEFT JOIN psp_marketing_revisions AS published
              ON published.page_key = state.page_key
             AND published.revision_id =
                 state.published_revision_id
            WHERE state.page_key = %s
            """,
            (section.key,),
        )

        row = cur.fetchone()

    if row is None:
        raise MarketingCMSNotFound(
            "Marketing content section state is missing."
        )

    return {
        "draft_revision_id": row[0],
        "draft_content": row[1],
        "published_revision_id": row[2],
        "published_content": row[3],
    }


def load_home_state(connection):
    """Backward-compatible Home Page state reader."""
    return load_section_state(
        connection,
        section_key=HOME_PAGE_KEY,
    )


def save_section_draft(
    connection,
    *,
    section_key,
    content,
    actor_id,
    expected_draft_revision_id,
):
    """Save one immutable registered-section draft revision.

    Lock the selected section state row to serialize concurrent edits.
    Reject stale submissions before inserting a revision.

    No published_revision_id is modified.
    """

    _check_actor_id(actor_id)
    _check_expected_revision(expected_draft_revision_id)

    section = get_section_spec(section_key)

    if section.key == HOME_PAGE_KEY:
        normalized = normalize_home_content(content)
    elif section.key == "home.promo":
        normalized = normalize_home_promotion_content(content)
    elif section.key == "home.peachweb":
        normalized = normalize_home_peachweb_content(content)
    elif section.key == "home.peachbook":
        normalized = normalize_home_peachbook_content(content)
    else:
        raise MarketingCMSSectionError(
            "Draft saving is not yet supported for this section."
        )

    if connection.autocommit:
        raise MarketingCMSConfigurationError(
            "Draft saving requires a database transaction."
        )

    try:
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT draft_revision_id
                FROM psp_marketing_page_state
                WHERE page_key = %s
                FOR UPDATE
                """,
                (section.key,),
            )

            row = cur.fetchone()

            if row is None:
                raise MarketingCMSNotFound(
                    "Marketing content section state is missing."
                )

            current_draft_id = row[0]

            if current_draft_id != expected_draft_revision_id:
                raise MarketingCMSConflict(
                    "This draft has changed. Reload before saving."
                )

            cur.execute(
                """
                SELECT COALESCE(
                    MAX(revision_number), 0
                ) + 1
                FROM psp_marketing_revisions
                WHERE page_key = %s
                """,
                (section.key,),
            )

            revision_number = int(cur.fetchone()[0])

            cur.execute(
                """
                INSERT INTO psp_marketing_revisions (
                    page_key,
                    revision_number,
                    content,
                    created_by
                )
                VALUES (%s, %s, %s, %s)
                RETURNING revision_id
                """,
                (
                    section.key,
                    revision_number,
                    Json(normalized),
                    actor_id,
                ),
            )

            revision_id = int(cur.fetchone()[0])

            cur.execute(
                """
                UPDATE psp_marketing_page_state
                SET draft_revision_id = %s,
                    updated_at = NOW()
                WHERE page_key = %s
                """,
                (revision_id, section.key),
            )

            if cur.rowcount != 1:
                raise MarketingCMSNotFound(
                    "Unable to update marketing section draft state."
                )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    return {
        "page_key": section.key,
        "revision_id": revision_id,
        "revision_number": revision_number,
        "content": normalized,
    }


def save_home_draft(
    connection,
    *,
    content,
    actor_id,
    expected_draft_revision_id,
):
    """Backward-compatible Home Page draft-saving interface."""
    return save_section_draft(
        connection,
        section_key=HOME_PAGE_KEY,
        content=content,
        actor_id=actor_id,
        expected_draft_revision_id=expected_draft_revision_id,
    )
