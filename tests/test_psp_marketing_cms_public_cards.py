"""Published-only Packages and Pricing template integration tests."""
import copy
import unittest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from services.psp_marketing_cms_product_baseline import get_product_baseline

PAGES = {
    'packages': 'psp_packages.html',
    'pricing': 'psp_pricing.html',
}
BASE = Path('templates/public_site')


def env():
    return Environment(
        loader=FileSystemLoader('templates'),
        autoescape=select_autoescape(['html']),
    )


def render_card(key, surface, product):
    template = env().get_template('public_site/psp_product_published_card.html')
    return template.render(
        cms_card_product=product, cms_card_key=key, cms_surface=surface,
    )


class PublicMarketingCardsTests(unittest.TestCase):
    def test_both_public_pages_parse_with_jinja(self):
        for name in PAGES.values():
            with self.subTest(name=name):
                env().get_template('public_site/' + name)

    def test_all_four_products_use_independent_published_fallback(self):
        for filename in PAGES.values():
            source = (BASE / filename).read_text()
            for key in ('solo', 'peachpos', 'team', 'collective'):
                with self.subTest(filename=filename, key=key):
                    self.assertIn("cms_products.get('" + key + "')", source)
            self.assertEqual(source.count('{% if cms_card_product %}'), 4)
            self.assertGreaterEqual(source.count('{% else %}'), 4)
            self.assertEqual(source.count('psp_product_published_card.html'), 4)

    def test_full_pages_use_solo_publication_and_pos_static_fallback(self):
        data = copy.deepcopy(get_product_baseline('solo'))
        data['shared']['name'] = 'Published-Solo-30AT'
        for surface, name in PAGES.items():
            with self.subTest(surface=surface):
                html = env().get_template('public_site/' + name).render(
                    cms_products={'solo': data},
                    cms_intro=None,
                    url_for=lambda *args, **kwargs: '/static/example.png',
                )
                self.assertIn('Published-Solo-30AT', html)
                self.assertIn('PeachPOS', html)
                self.assertIn('Peach Collective', html)

    def test_full_pages_keep_all_original_cards_without_publication(self):
        for surface, name in PAGES.items():
            with self.subTest(surface=surface):
                html = env().get_template('public_site/' + name).render(
                    cms_products={}, cms_intro=None,
                    url_for=lambda *args, **kwargs: '/static/example.png',
                )
                for label in ('Solo', 'PeachPOS', 'Team', 'Peach Collective'):
                    self.assertIn(label, html)

    def test_published_solo_shows_editable_text(self):
        data = copy.deepcopy(get_product_baseline('solo'))
        data['shared']['name'] = 'Solo Custom Product'
        data['shared']['monthly_price'] = '$51'
        data['packages']['top_statement_1'] = 'Published Package Copy'
        html = render_card('solo', 'packages', data)
        self.assertIn('Solo Custom Product', html)
        self.assertIn('$51', html)
        self.assertIn('Published Package Copy', html)
        self.assertNotIn('class="amount"', html)

    def test_pricing_shows_first_ten_features_only(self):
        data = copy.deepcopy(get_product_baseline('solo'))
        data['shared']['features'] = [f'Feature-AT-{i:02}' for i in range(12)]
        html = render_card('solo', 'pricing', data)
        self.assertIn('Feature-AT-09', html)
        self.assertNotIn('Feature-AT-10', html)
        self.assertNotIn('Feature-AT-11', html)

    def test_packages_shows_all_features(self):
        data = copy.deepcopy(get_product_baseline('solo'))
        data['shared']['features'] = [f'Feature-AT-{i:02}' for i in range(12)]
        data['packages']['feature_headings'] = [
            {'before_feature': 3, 'text': 'Group Heading 30AT'},
        ]
        html = render_card('solo', 'packages', data)
        self.assertIn('Feature-AT-11', html)
        self.assertTrue(html.index('Group Heading 30AT') < html.index('Feature-AT-03'))

    def test_escapes_product_content(self):
        data = copy.deepcopy(get_product_baseline('solo'))
        data['shared']['name'] = '<script>alert(1)</script>'
        html = render_card('solo', 'packages', data)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_solo_and_pos_keep_supported_signup_paths(self):
        for key, expected in (('solo', '/signup/solo'), ('peachpos', '/signup/pos')):
            data = copy.deepcopy(get_product_baseline(key))
            data['shared']['status'] = 'available'
            for surface in PAGES:
                with self.subTest(key=key, surface=surface):
                    html = render_card(key, surface, data)
                    self.assertIn(f'href="{expected}"', html)

    def test_team_and_collective_cannot_enable_unavailable_signup(self):
        for key in ('team', 'collective'):
            data = copy.deepcopy(get_product_baseline(key))
            data['shared']['status'] = 'available'
            for surface in PAGES:
                with self.subTest(key=key, surface=surface):
                    html = render_card(key, surface, data)
                    self.assertNotIn('href="/signup/', html)
                    self.assertIn('Coming Soon', html)

    def test_price_changes_do_not_change_stripe(self):
        source = (BASE / 'psp_product_published_card.html').read_text()
        self.assertNotIn('stripe', source.casefold())
        self.assertNotIn('payment_intent', source.casefold())

    def test_original_static_cards_remain_in_templates(self):
        packages = (BASE / PAGES['packages']).read_text()
        pricing = (BASE / PAGES['pricing']).read_text()
        self.assertIn('PeachBook online booking', packages)
        self.assertIn('Peach Suite Pro Pricing', pricing)
        self.assertIn('Save two months with annual billing', pricing)
        self.assertIn('Available November 30', packages)


if __name__ == '__main__':
    unittest.main()
