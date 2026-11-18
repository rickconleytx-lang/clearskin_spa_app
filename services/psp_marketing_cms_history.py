"""Read-only revision and publication history for marketing CMS."""

from services.psp_marketing_cms_content import (
    normalize_home_content,
)


class MarketingCMSHistoryError(RuntimeError):
    """Stored revision history is missing or inconsistent."""


def load_home_history(connection):
    """Load the Home Page history without changing any records.

    Revision IDs are distinct from revision numbers.
    A draft is not considered published merely because it exists.
    """

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT draft_revision_id, published_revision_id
            FROM psp_marketing_page_state
            WHERE page_key = %s
            """,
            ("home",),
        )
        state = cur.fetchone()

        if state is None:
            raise MarketingCMSHistoryError(
                "Marketing Home Page state is missing."
            )

        draft_id, published_id = state

        cur.execute(
            """
            SELECT revision_id,
                   revision_number,
                   content,
                   created_by,
                   created_at,
                   change_note
            FROM psp_marketing_revisions
            WHERE page_key = %s
            ORDER BY revision_number DESC
            """,
            ("home",),
        )
        revision_rows = cur.fetchall()

        cur.execute(
            """
            SELECT publication_event_id,
                   revision_id,
                   previous_revision_id,
                   action,
                   performed_by,
                   performed_at
            FROM psp_marketing_publication_events
            WHERE page_key = %s
            ORDER BY publication_event_id DESC
            """,
            ("home",),
        )
        event_rows = cur.fetchall()

    revision_ids = set()
    revision_numbers = set()
    revisions = []

    for (
        revision_id,
        number,
        content,
        created_by,
        created_at,
        note,
    ) in revision_rows:
        if (
            revision_id in revision_ids
            or number in revision_numbers
        ):
            raise MarketingCMSHistoryError(
                "Duplicate marketing revision in history."
            )

        revision_ids.add(revision_id)
        revision_numbers.add(number)

        # Treat corrupted historical content as an error,
        # never as trusted HTML or an editable replacement.
        hero = normalize_home_content(content)["hero"]

        revisions.append({
            "revision_id": revision_id,
            "revision_number": number,
            "hero": hero,
            "created_by": created_by,
            "created_at": created_at,
            "change_note": note,
            "is_draft": revision_id == draft_id,
            "is_published": revision_id == published_id,
            "was_published": False,
        })

    for active_id in (draft_id, published_id):
        if (
            active_id is not None
            and active_id not in revision_ids
        ):
            raise MarketingCMSHistoryError(
                "Active marketing revision is missing."
            )

    published_ids = set()
    events = []

    for (
        event_id,
        revision_id,
        previous_id,
        action,
        performed_by,
        performed_at,
    ) in event_rows:
        if action not in ("publish", "restore"):
            raise MarketingCMSHistoryError(
                "Unsupported marketing publication event."
            )

        if (
            revision_id not in revision_ids
            or (
                previous_id is not None
                and previous_id not in revision_ids
            )
        ):
            raise MarketingCMSHistoryError(
                "Publication event references a missing revision."
            )

        published_ids.add(revision_id)

        events.append({
            "publication_event_id": event_id,
            "revision_id": revision_id,
            "previous_revision_id": previous_id,
            "action": action,
            "performed_by": performed_by,
            "performed_at": performed_at,
        })

    if (
        published_id is not None
        and published_id not in published_ids
    ):
        raise MarketingCMSHistoryError(
            "Published revision has no publication event."
        )

    for revision in revisions:
        revision["was_published"] = (
            revision["revision_id"] in published_ids
        )

    return {
        "draft_revision_id": draft_id,
        "published_revision_id": published_id,
        "revisions": revisions,
        "events": events,
    }
