"""Validation for Peach Suite Pro corporate marketing content.

Corporate CMS content is separate from customer PeachWeb settings.
Validation does not save, publish, or access the database.
"""

HOME_HERO_LIMITS = {
    "primary_button_text": 80,
    "secondary_button_text": 80,
    "pricing_sentence": 300,
}


class MarketingContentError(ValueError):
    """Invalid or unsupported marketing content."""


def normalize_home_content(payload):
    """Validate a complete Home Page hero-section snapshot."""

    if not isinstance(payload, dict):
        raise MarketingContentError(
            "Home Page content must be an object."
        )

    if set(payload) != {"hero"}:
        raise MarketingContentError(
            "Only the Home Page hero section is supported."
        )

    hero = payload["hero"]

    if not isinstance(hero, dict):
        raise MarketingContentError(
            "Hero content must be an object."
        )

    if set(hero) != set(HOME_HERO_LIMITS):
        raise MarketingContentError(
            "Hero content contains missing or unsupported fields."
        )

    normalized = {}

    for field, maximum in HOME_HERO_LIMITS.items():
        value = hero[field]

        if not isinstance(value, str):
            raise MarketingContentError(
                f"{field} must be text."
            )

        value = value.strip()

        if not value:
            raise MarketingContentError(
                f"{field} cannot be empty."
            )

        if len(value) > maximum:
            raise MarketingContentError(
                f"{field} exceeds its character limit."
            )

        if any(ord(character) < 32 for character in value):
            raise MarketingContentError(
                f"{field} contains control characters."
            )

        if "<" in value or ">" in value:
            raise MarketingContentError(
                f"{field} cannot contain HTML markup."
            )

        normalized[field] = value

    return {"hero": normalized}
