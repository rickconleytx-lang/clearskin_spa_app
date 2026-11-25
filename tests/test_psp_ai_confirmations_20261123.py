import ast
import re
import unittest
from pathlib import Path

from jinja2 import Environment


class AIConfirmationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.template = Path(
            "templates/master_admin_ai_financial.html"
        ).read_text()
        cls.app = Path("app.py").read_text()
        cls.tree = ast.parse(cls.app)

    def route(self, name):
        matches = [
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == name
        ]
        self.assertEqual(len(matches), 1)
        return ast.get_source_segment(self.app, matches[0])

    def test_template_parses(self):
        Environment().parse(self.template)

    def test_four_forms_use_confirmation_dialog(self):
        for kind in (
            "platform-limit", "platform-toggle",
            "business-limit", "business-toggle"
        ):
            self.assertIn(
                'data-ai-confirm="' + kind + '"',
                self.template
            )

    def test_old_prompts_removed(self):
        self.assertNotIn("Type exactly", self.template)
        self.assertNotIn(
            "Type this exact confirmation",
            self.template
        )

    def test_four_hidden_confirmation_fields(self):
        forms = re.findall(
            r"<form\b[^>]*>.*?</form>",
            self.template,
            re.DOTALL
        )
        self.assertEqual(len(forms), 4)
        for form in forms:
            self.assertIn(
                'type="hidden" name="confirmation" value=""',
                form
            )

    def test_cancel_and_yes_controls_exist(self):
        self.assertIn('id="aiConfirmDialog"', self.template)
        self.assertIn('id="aiConfirmCancel"', self.template)
        self.assertIn('id="aiConfirmYes"', self.template)
        self.assertIn("form.requestSubmit()", self.template)

    def test_three_routes_require_confirmation(self):
        for name in (
            "master_admin_ai_monthly_limit",
            "master_admin_ai_platform_control",
            "master_admin_ai_business_control"
        ):
            self.assertIn(
                '!= "confirmed"', self.route(name)
            )

    def test_old_backend_phrase_checks_removed(self):
        for name in (
            "master_admin_ai_monthly_limit",
            "master_admin_ai_platform_control",
            "master_admin_ai_business_control"
        ):
            body = self.route(name)
            self.assertNotIn("required_confirmation", body)
            self.assertNotIn(
                "confirmation did not match", body
            )


if __name__ == "__main__":
    unittest.main()
