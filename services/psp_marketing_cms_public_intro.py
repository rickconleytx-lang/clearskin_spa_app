"""Read-only published introductions for public marketing pages.

This service never uses draft content as a public replacement.
The public route is responsible for connection cleanup and
falling back to the existing static website on read failures.
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
    load_section_state,
)


def load_published_intro(connection, *, section_key):
    """Return validated published heading/paragraph, or None."""
    section = get_section_spec(section_key)

    if section.key not in INTRO_SECTION_KEYS:
        raise MarketingCMSSectionError(
            "Public introduction reader supports introductions only."
        )

    state = load_section_state(
        connection,
        section_key=section.key,
    )

    published_id = state["published_revision_id"]
    published_content = state["published_content"]

    # No publication means the original public wording stays.
    if published_id is None and published_content is None:
        return None

    # A broken reference must not become a public override.
    if published_id is None or published_content is None:
        raise ValueError(
            "Published introduction state is inconsistent."
        )

    if (
        type(published_id) is not int
        or not 0 < published_id <= 9223372036854775807
    ):
        raise ValueError(
            "Invalid published introduction revision ID."
        )

    # Validate the complete stored snapshot. Return only text,
    # never trusted HTML, and never draft_content.
    normalized = normalize_page_intro_content(
        section.key,
        published_content,
    )

    return normalized["intro"]
