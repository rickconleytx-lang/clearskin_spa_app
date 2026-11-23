"""Private Master Admin product editor form handling.

No database access, Stripe operations, or publication.
"""

import re

from services.psp_marketing_cms_content import MarketingContentError
from services.psp_marketing_cms_product_content import (
    PAGE_TEXT_FIELDS,
    SHARED_TEXT_FIELDS,
    normalize_product_content,
)


def blank_product_content(label, status):
    """Unsaved editor placeholders, never public CMS content."""
    shared = {field: "" for field in SHARED_TEXT_FIELDS}
    shared.update({
        "status": status,
        "name": label,
        "features": [],
    })

    pages = {
        surface: {field: "" for field in PAGE_TEXT_FIELDS}
        for surface in ("packages", "pricing")
    }
    pages["packages"]["feature_headings"] = []

    return {"shared": shared, **pages}


def format_feature_headings(headings):
    return "\n".join(
        f'{heading["before_feature"] + 1} | {heading["text"]}'
        for heading in headings
    )


def parse_product_form(form):
    """Convert only known form fields to one validated snapshot."""
    shared = {
        field: form.get(f"shared__{field}", "")
        for field in SHARED_TEXT_FIELDS
    }
    shared["status"] = form.get("shared__status", "")
    shared["features"] = [
        line.strip()
        for line in form.get("features_text", "").splitlines()
        if line.strip()
    ]

    pages = {
        surface: {
            field: form.get(f"{surface}__{field}", "")
            for field in PAGE_TEXT_FIELDS
        }
        for surface in ("packages", "pricing")
    }

    headings = []
    for line in form.get(
        "packages_feature_headings_text", ""
    ).splitlines():
        line = line.strip()
        if not line:
            continue

        match = re.fullmatch(r"([0-9]{1,3})\s*\|\s*(.+)", line)
        if match is None:
            raise MarketingContentError(
                "Feature headings must use: 1 | Heading text"
            )

        number = int(match.group(1))
        if number < 1:
            raise MarketingContentError(
                "Feature heading positions start at 1."
            )

        headings.append({
            "before_feature": number - 1,
            "text": match.group(2).strip(),
        })

    pages["packages"]["feature_headings"] = headings

    return normalize_product_content({
        "shared": shared,
        **pages,
    })
