import ast
import re
import unittest
from pathlib import Path

from services.psp_ai_optional_reason import (
    normalize_limit_change_reason,
)


class OptionalAIReasonTests(unittest.TestCase):

    def test_empty_reason(self):
        result = normalize_limit_change_reason("")
        self.assertIn("Reason not provided", result)

    def test_whitespace_reason(self):
        result = normalize_limit_change_reason("   ")
        self.assertIn("Reason not provided", result)

    def test_short_reason(self):
        self.assertEqual(
            normalize_limit_change_reason("Testing"),
            "Admin note: Testing",
        )

    def test_normal_reason_preserved(self):
        reason = "Annual budget adjustment"
        self.assertEqual(
            normalize_limit_change_reason(reason),
            reason,
        )

    def test_internal_whitespace_normalized(self):
        self.assertEqual(
            normalize_limit_change_reason("Annual   budget adjustment"),
            "Annual budget adjustment",
        )

    def test_invalid_reason_type_rejected(self):
        with self.assertRaises(ValueError):
            normalize_limit_change_reason(None)

    def test_only_routine_forms_have_optional_reasons(self):
        template = Path(
            "templates/master_admin_ai_financial.html"
        ).read_text()

        forms = re.findall(
            r"<form\b[^>]*>.*?</form>",
            template,
            re.DOTALL,
        )
        self.assertEqual(len(forms), 4)

        for form in forms:
            match = re.search(
                r'<textarea\b[^>]*name="reason"[^>]*>',
                form,
                re.DOTALL,
            )
            self.assertIsNotNone(match)

            opening = match.group(0)

            if (
                'data-ai-confirm="platform-limit"' in form
                or 'data-ai-confirm="business-limit"' in form
            ):
                self.assertNotIn("required", opening)
                self.assertNotIn('minlength="10"', opening)
            else:
                self.assertIn("required", opening)
                self.assertIn('minlength="10"', opening)

    def test_routine_routes_use_normalization(self):
        source = Path("app.py").read_text()
        tree = ast.parse(source)

        for name in (
            "master_admin_ai_monthly_limit",
            "master_admin_ai_business_control",
        ):
            matches = [
                node for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.name == name
            ]
            self.assertEqual(len(matches), 1)
            body = ast.get_source_segment(source, matches[0])
            self.assertIn("normalize_limit_change_reason", body)


if __name__ == "__main__":
    unittest.main()
