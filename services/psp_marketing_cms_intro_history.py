"""Read-only revision history for marketing page introductions.

Packages and Pricing remain independent CMS sections.
No Flask routes, database connections, or writes are created here.
"""

from services.psp_marketing_cms_history import (
    MarketingCMSHistoryError,
)
from services.psp_marketing_cms_page_intro import (
    INTRO_SECTION_KEYS,
    normalize_page_intro_content,
)
from services.psp_marketing_cms_sections import (
    MarketingCMSSectionError,
    get_section_spec,
)


def load_intro_history(connection, *, section_key):
    """Load and validate one introduction's revision history."""
    section = get_section_spec(section_key)

    if section.key not in INTRO_SECTION_KEYS:
        raise MarketingCMSSectionError(
            "History supports page introductions only."
        )

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT draft_revision_id, published_revision_id
            FROM psp_marketing_page_state
            WHERE page_key = %s
            """,
            (section.key,),
        )

        state = cur.fetchone()

        if state is None:
            raise MarketingCMSHistoryError(
                "Introduction publication state is missing."
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
            (section.key,),
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
            (section.key,),
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
                "Duplicate introduction revision in history."
            )

        revision_ids.add(revision_id)
        revision_numbers.add(number)

        # Historical content is always validated as text,
        # never treated as trusted HTML.
        intro = normalize_page_intro_content(
            section.key,
            content,
        )["intro"]

        revisions.append({
            "revision_id": revision_id,
            "revision_number": number,
            "intro": intro,
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
                "Active introduction revision is missing."
            )

    published_ids = set()
    event_ids = set()
    events = []

    for (
        event_id,
        revision_id,
        previous_id,
        action,
        performed_by,
        performed_at,
    ) in event_rows:
        if event_id in event_ids:
            raise MarketingCMSHistoryError(
                "Duplicate introduction publication event."
            )

        event_ids.add(event_id)

        if action not in ("publish", "restore"):
            raise MarketingCMSHistoryError(
                "Unsupported introduction publication action."
            )

        if (
            revision_id not in revision_ids
            or (
                previous_id is not None
                and previous_id not in revision_ids
            )
        ):
            raise MarketingCMSHistoryError(
                "Introduction publication event references "
                "a missing revision."
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
            "Published introduction has no publication event."
        )

    for revision in revisions:
        revision["was_published"] = (
            revision["revision_id"] in published_ids
        )

    return {
        "page_key": section.key,
        "draft_revision_id": draft_id,
        "published_revision_id": published_id,
        "revisions": revisions,
        "events": events,
    }
