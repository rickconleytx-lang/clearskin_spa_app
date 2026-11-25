import unittest
from unittest.mock import patch

from services.psp_marketing_cms_content import (
    MarketingContentError,
)
from services.psp_marketing_cms_sections import (
    MarketingCMSSectionError,
)
from services import psp_marketing_cms_showcase_preview as preview


def showcase_content(caption, *, namespace=None):
    result = {
        "showcase": {
            "image_public_id": "",
            "image_url": "",
            "image_alt": "",
            "caption": caption,
        }
    }

    if namespace is not None:
        public_id = (
            "peach-suite-pro/marketing-cms/showcases/"
            f"{namespace}/" + "a" * 32
        )
        result["showcase"].update({
            "image_public_id": public_id,
            "image_url": (
                "https://res.cloudinary.com/example/image/upload/"
                f"v1234567890/{public_id}.png"
            ),
            "image_alt": "Example showcase image",
        })

    return result


def state(
    *,
    draft_id=None,
    draft=None,
    published_id=None,
    published=None,
):
    return {
        "draft_revision_id": draft_id,
        "draft_content": draft,
        "published_revision_id": published_id,
        "published_content": published,
    }


def default_states():
    return {
        "home.peachweb": state(
            draft_id=11,
            draft=showcase_content("PRIVATE WEB DRAFT"),
        ),
        "home.peachbook": state(
            draft_id=21,
            draft=showcase_content("PRIVATE BOOK DRAFT"),
        ),
    }


def default_home():
    return state()


class ShowcasePreviewContextTests(unittest.TestCase):

    def build(self, target="peachweb", *, sections=None, home=None):
        if sections is None:
            sections = default_states()
        if home is None:
            home = default_home()

        connection = object()

        def lookup(conn, *, section_key):
            self.assertIs(conn, connection)
            return sections[section_key]

        with (
            patch.object(
                preview,
                "load_section_state",
                side_effect=lookup,
            ) as section_loader,
            patch.object(
                preview,
                "load_home_state",
                return_value=home,
            ) as home_loader,
        ):
            result = preview.build_showcase_preview_context(
                connection,
                showcase=target,
            )

        return result, section_loader, home_loader

    def test_peachweb_uses_own_private_draft(self):
        context, _, _ = self.build("peachweb")

        self.assertTrue(context["cms_preview"])
        self.assertEqual(
            context["cms_peachweb_showcase"]["caption"],
            "PRIVATE WEB DRAFT",
        )
        self.assertNotIn("cms_peachbook_showcase", context)

    def test_peachbook_uses_own_private_draft(self):
        context, _, _ = self.build("peachbook")

        self.assertEqual(
            context["cms_peachbook_showcase"]["caption"],
            "PRIVATE BOOK DRAFT",
        )
        self.assertNotIn("cms_peachweb_showcase", context)

    def test_other_unpublished_draft_never_appears(self):
        sections = default_states()
        sections["home.peachbook"]["draft_content"] = (
            showcase_content("SECRET OTHER DRAFT")
        )

        context, _, _ = self.build(
            "peachweb",
            sections=sections,
        )

        self.assertNotIn("cms_peachbook_showcase", context)
        self.assertNotIn(
            "SECRET OTHER DRAFT",
            str(context),
        )

    def test_other_published_showcase_is_displayed(self):
        sections = default_states()
        sections["home.peachbook"].update({
            "published_revision_id": 9,
            "published_content": showcase_content(
                "PUBLIC BOOK CAPTION"
            ),
        })

        context, _, _ = self.build(
            "peachweb",
            sections=sections,
        )

        self.assertEqual(
            context["cms_peachbook_showcase"]["caption"],
            "PUBLIC BOOK CAPTION",
        )
        self.assertNotIn(
            "PRIVATE BOOK DRAFT",
            str(context),
        )

    def test_published_hero_is_used(self):
        home = state(
            draft_id=30,
            draft={"hero": {"private": "NEVER SHOW"}},
            published_id=25,
            published={
                "hero": {
                    "primary_button_text": "Start Trial",
                    "secondary_button_text": "View Pricing",
                    "pricing_sentence": "Plans start at $49.",
                }
            },
        )

        context, _, _ = self.build(home=home)

        self.assertEqual(
            context["cms_home_hero"]["primary_button_text"],
            "Start Trial",
        )
        self.assertNotIn("NEVER SHOW", str(context))

    def test_missing_target_draft_returns_none(self):
        sections = default_states()
        sections["home.peachweb"] = state()

        context, section_loader, home_loader = self.build(
            sections=sections,
        )

        self.assertIsNone(context)
        self.assertEqual(section_loader.call_count, 1)
        home_loader.assert_not_called()

    def test_invalid_target_content_is_rejected(self):
        sections = default_states()
        sections["home.peachweb"]["draft_content"] = {
            "showcase": {"caption": 123}
        }

        with self.assertRaises(MarketingContentError):
            self.build(sections=sections)

    def test_cross_showcase_image_is_rejected(self):
        sections = default_states()
        sections["home.peachbook"]["draft_content"] = (
            showcase_content(
                "Wrong picture namespace",
                namespace="peachweb",
            )
        )

        with self.assertRaises(MarketingContentError):
            self.build(
                "peachbook",
                sections=sections,
            )

    def test_inconsistent_other_publication_is_rejected(self):
        sections = default_states()
        sections["home.peachbook"][
            "published_revision_id"
        ] = 9

        with self.assertRaises(ValueError):
            self.build(sections=sections)

    def test_invalid_published_hero_is_rejected(self):
        home = state(
            published_id=1,
            published={"hero": {"invalid": "data"}},
        )

        with self.assertRaises(MarketingContentError):
            self.build(home=home)

    def test_inconsistent_target_state_is_rejected(self):
        sections = default_states()
        sections["home.peachweb"]["draft_revision_id"] = None

        with self.assertRaises(ValueError):
            self.build(sections=sections)

    def test_unknown_showcase_rejected_before_database(self):
        with patch.object(
            preview,
            "load_section_state",
        ) as loader:
            with self.assertRaises(
                MarketingCMSSectionError
            ):
                preview.build_showcase_preview_context(
                    object(),
                    showcase="home",
                )

        loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
