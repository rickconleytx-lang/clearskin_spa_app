"""Read-only private marketing showcase preview preparation.

Only the selected showcase uses draft content.
All other page components use published content or fallbacks.
No database connection, transaction, or publication is performed here.
"""

from services.psp_marketing_cms_content import (
    normalize_home_content,
    normalize_home_peachbook_content,
    normalize_home_peachweb_content,
)
from services.psp_marketing_cms_sections import (
    MarketingCMSSectionError,
    get_section_spec,
)
from services.psp_marketing_cms_service import (
    load_home_state,
    load_section_state,
)


_SHOWCASES = {
    "peachweb": (
        "home.peachweb",
        "cms_peachweb_showcase",
        normalize_home_peachweb_content,
    ),
    "peachbook": (
        "home.peachbook",
        "cms_peachbook_showcase",
        normalize_home_peachbook_content,
    ),
}


def _check_state_pair(state, *, revision_field, content_field):
    revision = state[revision_field]
    content = state[content_field]

    if (revision is None) != (content is None):
        raise ValueError(
            "Marketing CMS revision and content state mismatch."
        )


def build_showcase_preview_context(
    connection,
    *,
    showcase,
):
    """Prepare one showcase draft against published-only surroundings.

    Returns None when the selected showcase has no saved draft.
    The calling private route owns rollback and connection cleanup.
    """

    if showcase not in _SHOWCASES:
        raise MarketingCMSSectionError(
            "Unsupported marketing showcase preview."
        )

    target_key, target_variable, target_validator = (
        _SHOWCASES[showcase]
    )

    get_section_spec(target_key)

    target_state = load_section_state(
        connection,
        section_key=target_key,
    )

    _check_state_pair(
        target_state,
        revision_field="draft_revision_id",
        content_field="draft_content",
    )

    if target_state["draft_content"] is None:
        return None

    context = {
        "cms_preview": True,
        target_variable: target_validator(
            target_state["draft_content"]
        )["showcase"],
    }

    # Never use another showcase's unpublished draft.
    other_name = (
        "peachbook"
        if showcase == "peachweb"
        else "peachweb"
    )

    other_key, other_variable, other_validator = (
        _SHOWCASES[other_name]
    )

    other_state = load_section_state(
        connection,
        section_key=other_key,
    )

    _check_state_pair(
        other_state,
        revision_field="published_revision_id",
        content_field="published_content",
    )

    if other_state["published_content"] is not None:
        context[other_variable] = other_validator(
            other_state["published_content"]
        )["showcase"]

    # Never use an unpublished Home Page hero in a showcase preview.
    home_state = load_home_state(connection)

    _check_state_pair(
        home_state,
        revision_field="published_revision_id",
        content_field="published_content",
    )

    if home_state["published_content"] is not None:
        context["cms_home_hero"] = normalize_home_content(
            home_state["published_content"]
        )["hero"]

    return context
