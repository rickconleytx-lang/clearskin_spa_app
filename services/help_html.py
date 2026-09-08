"""
Peach Suite Pro Help and Support HTML sanitization.

Stored Help content may contain approved formatting HTML.
Before that content is rendered on a public surface, it must
pass through this allowlist sanitizer.

Do not use MarkupSafe alone as a sanitizer. MarkupSafe controls
escaping/trust but does not remove unsafe HTML.
"""

import nh3


_HELP_ALLOWED_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "small",
    "span",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}


_HELP_ALLOWED_ATTRIBUTES = {
    "a": {
        "href",
        "title",
    },
    "img": {
        "src",
        "alt",
        "title",
        "style",
        "width",
        "height",
    },
    "p": {
        "style",
    },
    "span": {
        "style",
    },
    "div": {
        "style",
    },
    "td": {
        "colspan",
        "rowspan",
    },
    "th": {
        "colspan",
        "rowspan",
        "scope",
    },
}


_HELP_RESTRICTED_ATTRIBUTE_VALUES = {
    "a": {
        "target": {
            "_blank",
            "_self",
        },
    },
    "ol": {
        "type": {
            "1",
            "A",
            "a",
            "I",
            "i",
        },
    },
}


_HELP_ALLOWED_STYLE_PROPERTIES = {
    "border",
    "color",
    "cursor",
    "height",
    "max-width",
    "text-align",
    "width",
}


_HELP_CLEAN_CONTENT_TAGS = {
    "embed",
    "iframe",
    "object",
    "script",
    "style",
    "template",
}


_HELP_URL_SCHEMES = {
    "http",
    "https",
    "mailto",
    "tel",
}


def _help_relative_url(url):
    """
    Permit safe same-origin relative links and Help images.

    Protocol-relative URLs are rejected because they can silently
    load resources from another host.
    """

    url = str(url or "").strip()

    if url.startswith("//"):
        return None

    if (
        url.startswith("/")
        or url.startswith("#")
    ):
        return url

    return None


def _help_attribute_filter(tag, attribute, value):
    """
    Apply Help-specific attribute restrictions beyond nh3's
    generic allowlist.
    """

    value = str(value or "")

    # Stored Help content must never carry Jinja/template syntax
    # onto a public page.
    if any(
        marker in value
        for marker in (
            "{{",
            "}}",
            "{%",
            "%}",
        )
    ):
        return None

    # Public Help images are V1-local assets only. This prevents
    # arbitrary remote image/tracking URLs from being embedded.
    if tag == "img" and attribute == "src":
        if not value.startswith(
            "/static/help/images/"
        ):
            return None

    return value


def sanitize_help_html(html):
    """
    Return a sanitized HTML fragment suitable for public Help pages.

    The returned value is a plain string. A Jinja template may mark
    this already-sanitized result safe at the final render boundary.
    """

    return nh3.clean(
        str(html or ""),
        tags=_HELP_ALLOWED_TAGS,
        clean_content_tags=_HELP_CLEAN_CONTENT_TAGS,
        attributes=_HELP_ALLOWED_ATTRIBUTES,
        attribute_filter=_help_attribute_filter,
        tag_attribute_values=(
            _HELP_RESTRICTED_ATTRIBUTE_VALUES
        ),
        strip_comments=True,
        link_rel="noopener noreferrer",
        url_schemes=_HELP_URL_SCHEMES,
        filter_style_properties=(
            _HELP_ALLOWED_STYLE_PROPERTIES
        ),
        url_relative=_help_relative_url,
    )
