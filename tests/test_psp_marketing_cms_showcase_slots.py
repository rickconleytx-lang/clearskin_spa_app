import unittest
from pathlib import Path
from jinja2 import Environment


SOURCE = Path(
    "templates/public_site/psp_home.html"
).read_text(encoding="utf-8")

ENV = Environment(autoescape=True)


def section(label):
    marker = f"Introducing {label}"
    position = SOURCE.index(marker)
    start = SOURCE.rfind(
        '<section class="product-section',
        0,
        position,
    )
    end = SOURCE.index("</section>", position) + len("</section>")
    return SOURCE[start:end]


def sample(name, *, image=True, caption=True):
    return {
        "image_public_id": "",
        "image_url": (
            f"https://res.cloudinary.com/demo/image/upload/v1/{name}.png"
            if image else ""
        ),
        "image_alt": f"{name} sample picture" if image else "",
        "caption": (
            "First line\nSecond line" if caption else ""
        ),
    }


def render(label, **context):
    return ENV.from_string(section(label)).render(**context)


class ShowcaseDisplaySlotTests(unittest.TestCase):

    def test_peachweb_original_illustration_without_cms(self):
        html = render("PeachWeb")
        self.assertIn('class="mock-window"', html)
        self.assertIn('class="mock-content"', html)
        self.assertNotIn("<figure", html)
        self.assertNotIn("<img", html)

    def test_peachbook_original_illustration_without_cms(self):
        html = render("PeachBook")
        self.assertIn('class="mock-window"', html)
        self.assertIn('class="mock-content"', html)
        self.assertNotIn("<figure", html)
        self.assertNotIn("<img", html)

    def test_peachweb_image_and_multiline_caption(self):
        html = render(
            "PeachWeb",
            cms_peachweb_showcase=sample("peachweb"),
        )
        self.assertIn("peachweb.png", html)
        self.assertIn('alt="peachweb sample picture"', html)
        self.assertIn("First line\nSecond line", html)
        self.assertIn("white-space: pre-line", html)

    def test_peachbook_image_and_multiline_caption(self):
        html = render(
            "PeachBook",
            cms_peachbook_showcase=sample("peachbook"),
        )
        self.assertIn("peachbook.png", html)
        self.assertIn('alt="peachbook sample picture"', html)
        self.assertIn("First line\nSecond line", html)
        self.assertIn("white-space: pre-line", html)

    def test_peachweb_context_does_not_change_peachbook(self):
        html = render(
            "PeachBook",
            cms_peachweb_showcase=sample("peachweb"),
        )
        self.assertIn('class="mock-window"', html)
        self.assertNotIn("peachweb.png", html)

    def test_peachbook_context_does_not_change_peachweb(self):
        html = render(
            "PeachWeb",
            cms_peachbook_showcase=sample("peachbook"),
        )
        self.assertIn('class="mock-window"', html)
        self.assertNotIn("peachbook.png", html)

    def test_untrusted_caption_and_alt_are_escaped(self):
        content = sample("peachweb")
        content["image_alt"] = '<img onerror="alert(1)">'
        content["caption"] = "<script>alert(1)</script>"

        html = render(
            "PeachWeb",
            cms_peachweb_showcase=content,
        )

        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn('onerror="alert(1)"', html)

    def test_caption_only_uses_original_illustration(self):
        html = render(
            "PeachBook",
            cms_peachbook_showcase=sample(
                "peachbook",
                image=False,
            ),
        )
        self.assertIn('class="mock-window"', html)
        self.assertIn("First line\nSecond line", html)
        self.assertIn("<figcaption", html)

    def test_empty_showcase_uses_original_illustration(self):
        html = render(
            "PeachWeb",
            cms_peachweb_showcase=sample(
                "peachweb",
                image=False,
                caption=False,
            ),
        )
        self.assertIn('class="mock-window"', html)
        self.assertNotIn("<figure", html)

    def test_existing_marketing_copy_and_links_preserved(self):
        for label, heading, link in (
            (
                "PeachWeb",
                "Your website and your business should work together.",
                "Visit a PeachWeb Site",
            ),
            (
                "PeachBook",
                "Turn online visitors into booked customers.",
                "Visit a PeachBook Site",
            ),
        ):
            with self.subTest(label=label):
                html = render(label)
                self.assertIn(heading, html)
                self.assertIn(link, html)


if __name__ == "__main__":
    unittest.main()
