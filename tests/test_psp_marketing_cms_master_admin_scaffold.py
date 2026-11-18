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

    def test_initial_page_is_read_only(self):
        self.assertEqual(self.page.count("readonly"), 3)
        self.assertNotIn("<form", self.page.lower())
        self.assertNotIn(
            'type="submit"', self.page.lower()
        )


if __name__ == "__main__":
    unittest.main()
