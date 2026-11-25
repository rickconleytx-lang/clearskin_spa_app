"""Shared corporate marketing product feature handling.

Packages displays all features.
Pricing displays the first ten features.

No database, Flask route, or publication operations.
"""

from services.psp_marketing_cms_content import (
    MarketingContentError,
)

MAX_PRODUCT_FEATURES = 100
MAX_FEATURE_LENGTH = 100
PRICING_FEATURE_LIMIT = 10


def normalize_product_features(features):
    """Validate and preserve one ordered product feature list."""

    if not isinstance(features, list):
        raise MarketingContentError(
            "Product features must be a list."
        )

    if len(features) > MAX_PRODUCT_FEATURES:
        raise MarketingContentError(
            "Too many product features."
        )

    normalized = []

    for feature in features:
        if not isinstance(feature, str):
            raise MarketingContentError(
                "Every product feature must be text."
            )

        feature = feature.strip()

        if not feature or len(feature) > MAX_FEATURE_LENGTH:
            raise MarketingContentError(
                "A product feature is empty or too long."
            )

        if any(
            ord(char) < 32 or ord(char) == 127
            for char in feature
        ):
            raise MarketingContentError(
                "Product features cannot contain control characters."
            )

        if "<" in feature or ">" in feature:
            raise MarketingContentError(
                "Product features cannot contain HTML markup."
            )

        normalized.append(feature)

    return normalized


def packages_product_features(features):
    """Return all validated features in their saved order."""
    return normalize_product_features(features)


def pricing_product_features(features):
    """Return only the first ten validated features."""
    return normalize_product_features(features)[:PRICING_FEATURE_LIMIT]
