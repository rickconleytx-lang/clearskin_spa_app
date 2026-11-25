import unittest
from pathlib import Path

from jinja2 import Environment


class MarketingCMSMasterAdminScaffoldTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app_source = Path("app.py").read_text()
        cls.dashboard = Path(
            "templates/master_admin_home.html"
        ).read_text()
        cls.page = Path(
            "templates/master_admin_website_management.html"
        ).read_text()

    def test_app_python_syntax(self):
        compile(self.app_source, "app.py", "exec")

    def test_route_has_master_admin_protection(self):
        expected = """@app.route(
    "/master-admin/website",
    methods=["GET"],
)
@login_required
@master_admin_required
def master_admin_website_management():"""

        self.assertIn(expected, self.app_source)

    def test_dashboard_has_website_card(self):
        self.assertIn(
            "url_for('master_admin_website_management')",
            self.dashboard,
        )

    def test_page_template_parses(self):
        Environment().parse(self.page)

    def test_page_has_protected_draft_form(self):
        self.assertEqual(self.page.count("<form"), 1)
        self.assertEqual(self.page.count("</form>"), 1)
        self.assertIn('method="POST"', self.page)
        self.assertIn(
            "master_admin_website_save_draft",
            self.page,
        )
        self.assertIn(
            'name="security_csrf_token"',
            self.page,
        )
        self.assertIn(
            'name="expected_draft_revision_id"',
            self.page,
        )
        self.assertIn(
            'name="primary_button_text"',
            self.page,
        )
        self.assertIn(
            'name="secondary_button_text"',
            self.page,
        )
        self.assertIn(
            'name="pricing_sentence"',
            self.page,
        )
        self.assertEqual(
            self.page.count('type="submit"'), 1
        )
        self.assertNotIn("readonly", self.page)


if __name__ == "__main__":
    unittest.main()
