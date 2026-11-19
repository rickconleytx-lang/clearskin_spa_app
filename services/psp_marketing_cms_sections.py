"""Approved independently versioned corporate marketing sections.

The existing 'home' key is retained for historical Home Page
revisions. This module performs no database or network operations.
"""

from dataclasses import dataclass
from types import MappingProxyType


SURFACES = frozenset({
    "home",
    "packages",
    "pricing",
})


class MarketingCMSSectionError(ValueError):
    """Unknown or unsupported corporate marketing section."""


@dataclass(frozen=True)
class MarketingSection:
    key: str
    label: str
    kind: str
    surfaces: tuple


_SECTION_SPECS = (
    MarketingSection(
        "home",
        "Home Page Hero",
        "hero",
        ("home",),
    ),
    MarketingSection(
        "home.peachweb",
        "PeachWeb Showcase",
        "showcase",
        ("home",),
    ),
    MarketingSection(
        "home.peachbook",
        "PeachBook Showcase",
        "showcase",
        ("home",),
    ),
    MarketingSection(
        "product.solo",
        "Solo",
        "product",
        ("home", "packages", "pricing"),
    ),
    MarketingSection(
        "product.peachpos",
        "PeachPOS",
        "product",
        ("packages", "pricing"),
    ),
    MarketingSection(
        "product.team",
        "Team",
        "product",
        ("packages", "pricing"),
    ),
    MarketingSection(
        "product.collective",
        "Peach Collective",
        "product",
        ("packages", "pricing"),
    ),
    MarketingSection(
        "marketing.benefits",
        "Additional Services & Launch Benefits",
        "benefits",
        ("packages", "pricing"),
    ),
)


SECTION_REGISTRY = MappingProxyType({
    spec.key: spec
    for spec in _SECTION_SPECS
})


def get_section_spec(section_key):
    """Reject arbitrary section keys before database access."""

    if (
        not isinstance(section_key, str)
        or section_key not in SECTION_REGISTRY
    ):
        raise MarketingCMSSectionError(
            "Unsupported marketing content section."
        )

    return SECTION_REGISTRY[section_key]


def sections_for_surface(surface):
    """Return sections contributing content to a public page."""

    if not isinstance(surface, str) or surface not in SURFACES:
        raise MarketingCMSSectionError(
            "Unsupported marketing website page."
        )

    return tuple(
        spec
        for spec in _SECTION_SPECS
        if surface in spec.surfaces
    )
