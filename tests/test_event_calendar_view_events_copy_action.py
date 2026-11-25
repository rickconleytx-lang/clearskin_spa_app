"""EC-065-6: View Events Copy action regression contracts."""

from pathlib import Path
import re
import unittest

from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[1]

VIEW = (ROOT / "templates/event_view_events.html").read_text(
    encoding="utf-8"
)

EDIT = """<a class="ec-view-action" href="{{ url_for('event_new', edit=event.event_id) }}">Edit</a>"""

COPY = """<a class="ec-view-action" href="{{ url_for('event_new', copy=event.event_id) }}">Copy</a>"""


class EventViewCopyActionTests(unittest.TestCase):

    def test_copy_is_immediately_after_edit(self):
        pattern = (
            re.escape(EDIT)
            + r"\s*"
            + r"{% if not event\.is_archived %}"
            + r"\s*"
            + re.escape(COPY)
            + r"\s*"
            + r"{% endif %}"
        )

        self.assertIsNotNone(re.search(pattern, VIEW), "Copy must follow Edit for active events")

    def test_copy_uses_existing_event_id(self):
        self.assertEqual(VIEW.count(COPY), 1)

        app = (ROOT / "app.py").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'copy_raw = request.args.get("copy")',
            app
        )

        self.assertIn(
            "event_copy_id=copy_event_id",
            app
        )

    def test_view_events_template_parses(self):
        Environment().parse(VIEW)


if __name__ == "__main__":
    unittest.main()
