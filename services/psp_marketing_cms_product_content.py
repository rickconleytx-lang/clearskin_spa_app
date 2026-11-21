"""Validation for shared corporate marketing product content.

One product section supplies both Packages and Pricing.
This module performs no database or publishing operations.
"""

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_product_features import (
    normalize_product_features,
)

PRODUCT_STATUSES = frozenset({
    "available",
    "coming_soon",
    "planned",
    "discontinued",
})

SHARED_TEXT_FIELDS = {
    "bubble_text": 100,
    "name": 80,
    "monthly_price": 40,
    "annual_price": 40,
    "monthly_unit": 60,
    "annual_unit": 60,
}

PAGE_TEXT_FIELDS = {
    "top_statement_1": 600,
    "top_statement_2": 600,
    "button_text": 100,
    "bottom_heading": 150,
    "bottom_statement": 600,
}


def _text(value, field, maximum, *,
          required=False, multiline=False):
    if not isinstance(value, str):
        raise MarketingContentError(
            f"{field} must be text."
        )

    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.strip()

    if required and not value:
        raise MarketingContentError(
            f"{field} cannot be empty."
        )

    if len(value) > maximum:
        raise MarketingContentError(
            f"{field} is too long."
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

    return value


def _page_content(value, label, *, packages=False,
                  feature_count=0):
    required_keys = set(PAGE_TEXT_FIELDS)

    if packages:
        required_keys.add("feature_headings")

    if not isinstance(value, dict) or set(value) != required_keys:
        raise MarketingContentError(
            f"Invalid {label} content fields."
        )

    normalized = {}

    for field, maximum in PAGE_TEXT_FIELDS.items():
        normalized[field] = _text(
            value[field],
            f"{label}.{field}",
            maximum,
            required=(field == "button_text"),
            multiline=field in {
                "top_statement_1",
                "top_statement_2",
                "bottom_statement",
            },
        )

    if packages:
        headings = value["feature_headings"]

        if not isinstance(headings, list):
            raise MarketingContentError(
                "Feature headings must be a list."
            )

        if len(headings) > 20:
            raise MarketingContentError(
                "Too many feature headings."
            )

        normalized_headings = []
        previous = -1

        for heading in headings:
            if (
                not isinstance(heading, dict)
                or set(heading) != {
                    "before_feature", "text"
                }
            ):
                raise MarketingContentError(
                    "Invalid feature heading."
                )

            index = heading["before_feature"]

            if (
                type(index) is not int
                or index < 0
                or index >= feature_count
                or index <= previous
            ):
                raise MarketingContentError(
                    "Feature heading positions must "
                    "be valid and increasing."
                )

            normalized_headings.append({
                "before_feature": index,
                "text": _text(
                    heading["text"],
                    "feature heading",
                    150,
                    required=True,
                ),
            })

            previous = index

        normalized["feature_headings"] = normalized_headings

    return normalized


def normalize_product_content(payload):
    """Validate a complete independent product snapshot.

    The section key identifies Solo, PeachPOS, Team, or Collective.
    """

    if (
        not isinstance(payload, dict)
        or set(payload) != {
            "shared", "packages", "pricing"
        }
    ):
        raise MarketingContentError(
            "Product content must contain shared, "
            "packages, and pricing."
        )

    shared = payload["shared"]

    required = (
        set(SHARED_TEXT_FIELDS)
        | {"status", "features"}
    )

    if not isinstance(shared, dict) or set(shared) != required:
        raise MarketingContentError(
            "Invalid shared product fields."
        )

    if (
        not isinstance(shared["status"], str)
        or shared["status"] not in PRODUCT_STATUSES
    ):
        raise MarketingContentError(
            "Unsupported product status."
        )

    normalized_shared = {
        "status": shared["status"],
    }

    for field, maximum in SHARED_TEXT_FIELDS.items():
        normalized_shared[field] = _text(
            shared[field],
            f"shared.{field}",
            maximum,
            required=True,
        )

    features = normalize_product_features(
        shared["features"]
    )
    normalized_shared["features"] = features

    return {
        "shared": normalized_shared,
        "packages": _page_content(
            payload["packages"],
            "packages",
            packages=True,
            feature_count=len(features),
        ),
        "pricing": _page_content(
            payload["pricing"],
            "pricing",
        ),
    }
