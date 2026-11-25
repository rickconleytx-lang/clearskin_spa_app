"""Independent Packages and Pricing introduction content.

These are separate CMS sections with separate revisions.
No database, Flask route, or publication operations.
"""

from services.psp_marketing_cms_content import (
    MarketingContentError,
)

INTRO_SECTION_KEYS = frozenset({
    "packages.intro",
    "pricing.intro",
})

INTRO_HEADING_LIMIT = 200
INTRO_PARAGRAPH_LIMIT = 1200


def _validate_text(value, field, limit, *, multiline=False):
    if not isinstance(value, str):
        raise MarketingContentError(
            f"{field} must be text."
        )

    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.strip()

    if not value:
        raise MarketingContentError(
            f"{field} cannot be empty."
        )

    if len(value) > limit:
        raise MarketingContentError(
            f"{field} exceeds its character limit."
        )

    if any(
        (ord(char) < 32 and
         (char != "\n" or not multiline))
        or ord(char) == 127
        for char in value
    ):
        raise MarketingContentError(
            f"{field} contains control characters."
        )

    if "<" in value or ">" in value:
        raise MarketingContentError(
            f"{field} cannot contain HTML markup."
        )

    if multiline and len(value.split("\n")) > 10:
        raise MarketingContentError(
            f"{field} contains too many lines."
        )

    return value


def normalize_page_intro_content(section_key, payload):
    """Validate one independent page introduction snapshot."""

    if section_key not in INTRO_SECTION_KEYS:
        raise MarketingContentError(
            "Unsupported introduction section."
        )

    if (
        not isinstance(payload, dict)
        or set(payload) != {"intro"}
    ):
        raise MarketingContentError(
            "Introduction content must contain only intro."
        )

    intro = payload["intro"]

    if (
        not isinstance(intro, dict)
        or set(intro) != {"heading", "paragraph"}
    ):
        raise MarketingContentError(
            "Invalid introduction fields."
        )

    return {
        "intro": {
            "heading": _validate_text(
                intro["heading"],
                "heading",
                INTRO_HEADING_LIMIT,
            ),
            "paragraph": _validate_text(
                intro["paragraph"],
                "paragraph",
                INTRO_PARAGRAPH_LIMIT,
                multiline=True,
            ),
        }
    }
