"""Tests for Packages and Pricing introduction history display."""
import copy
import unittest
from pathlib import Path
from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape


def example_history():
    return {
        'page_key': 'packages.intro',
        'draft_revision_id': 9,
        'published_revision_id': 9,
        'revisions': [
            {'revision_id': 9, 'revision_number': 2,
             'intro': {'heading': 'Original Promotion', 'paragraph': 'Use LAUNCH10 to save.'},
             'created_by': 9, 'created_at': 'November 21', 'change_note': None,
             'is_draft': True, 'is_published': True, 'was_published': True},
            {'revision_id': 6, 'revision_number': 1,
             'intro': {'heading': 'TEST Promotion', 'paragraph': 'Temporary test.'},
             'created_by': 9, 'created_at': 'November 20', 'change_note': None,
             'is_draft': False, 'is_published': False, 'was_published': False},
        ],
        'events': [
            {'publication_event_id': 4, 'revision_id': 9, 'previous_revision_id': None,
             'action': 'publish', 'performed_by': 9, 'performed_at': 'November 21'},
        ],
    }


class IntroHistoryTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path('templates/master_admin_website_intro_history.html').read_text()
        cls.env = Environment(
            loader=DictLoader({
                'base.html': '{% block content %}{% endblock %}',
                'history.html': cls.source,
            }),
            autoescape=select_autoescape(enabled_extensions=('html',), default=True),
            undefined=StrictUndefined,
        )

    def render(self, surface='packages', history=None):
        return self.env.get_template('history.html').render(
            surface=surface,
            page_label='Subscription Packages' if surface == 'packages' else 'Pricing',
            history=copy.deepcopy(history if history is not None else example_history()),
            url_for=lambda endpoint, **kwargs: '/test/' + endpoint + (
                '/' + kwargs['surface'] if 'surface' in kwargs else ''
            ),
        )

    def test_template_compiles(self):
        self.env.parse(self.source)

    def test_packages_heading(self):
        self.assertIn('Subscription Packages Introduction', self.render())

    def test_pricing_heading(self):
        self.assertIn('Pricing Introduction', self.render(surface='pricing'))

    def test_current_draft_and_publication(self):
        output = self.render()
        self.assertIn('Current Introduction State', output)
        self.assertGreaterEqual(output.count('Revision ID 9'), 2)

    def test_revision_number_distinct_from_database_id(self):
        output = self.render()
        self.assertIn('Revision 2', output)
        self.assertIn('Revision 1', output)
        self.assertIn('Revision ID:', output)

    def test_published_revision_status(self):
        self.assertIn('Currently Published', self.render())

    def test_unpublished_test_draft_status(self):
        output = self.render()
        self.assertIn('Never Published', output)
        self.assertIn('TEST Promotion', output)

    def test_unpublished_revision_cannot_offer_restore(self):
        output = self.render()
        self.assertNotIn('Review Restoration', output)
        self.assertIn('cannot be restored', output)

    def test_older_published_revision_offers_review(self):
        history = example_history()
        history['revisions'][1]['was_published'] = True
        output = self.render(history=history)
        self.assertIn('Review Restoration', output)
        self.assertIn('revision_id=6', output)

    def test_restore_url_is_pricing_scoped(self):
        history = example_history()
        history['revisions'][1]['was_published'] = True
        output = self.render(surface='pricing', history=history)
        self.assertIn('/test/master_admin_website_intro_restore_review/pricing', output)

    def test_current_publication_not_restorable(self):
        history = example_history()
        history['revisions'] = history['revisions'][:1]
        self.assertNotIn('Review Restoration', self.render(history=history))

    def test_no_current_publication_hides_restore(self):
        history = example_history()
        history['published_revision_id'] = None
        history['revisions'][0]['is_published'] = False
        history['revisions'][1]['was_published'] = True
        self.assertNotIn('Review Restoration', self.render(history=history))

    def test_publication_event_details(self):
        output = self.render()
        self.assertIn('Publication Activity', output)
        self.assertIn('Publication Event ID:', output)
        self.assertIn('first publication', output)

    def test_empty_history(self):
        history = dict(page_key='pricing.intro', draft_revision_id=None,
                       published_revision_id=None, revisions=[], events=[])
        output = self.render(surface='pricing', history=history)
        self.assertIn('No saved introduction revisions yet.', output)
        self.assertIn('No publication events have been recorded.', output)

    def test_html_escapes_historical_heading(self):
        history = example_history()
        history['revisions'][0]['intro']['heading'] = '<script>alert(1)</script>'
        output = self.render(history=history)
        self.assertNotIn('<script>', output)
        self.assertIn('&lt;script&gt;', output)

    def test_history_is_read_only(self):
        output = self.render()
        self.assertNotIn('<form', output)
        self.assertNotIn('method="POST"', output)
        self.assertIn('Back to Introduction Editor', output)


if __name__ == '__main__':
    unittest.main()
