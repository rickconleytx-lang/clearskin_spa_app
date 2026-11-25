import unittest
from decimal import Decimal
from pathlib import Path
from jinja2 import Environment

from services.psp_ai_financial_reporting import (
    sum_business_ai_monthly_limits,
)


class AIManagementSummaryTests(unittest.TestCase):

    def test_two_businesses_total_four_dollars(self):
        self.assertEqual(
            sum_business_ai_monthly_limits([
                {"spa_id": 1, "monthly_limit_usd": "2.00"},
                {"spa_id": 2, "monthly_limit_usd": "2.00"},
            ]),
            Decimal("4.00"),
        )

    def test_enabled_and_disabled_count(self):
        self.assertEqual(
            sum_business_ai_monthly_limits([
                {"spa_id": 1, "monthly_limit_usd": "2.00",
                 "ai_enabled": True},
                {"spa_id": 2, "monthly_limit_usd": "3.50",
                 "ai_enabled": False},
            ]),
            Decimal("5.50"),
        )

    def test_unconfigured_excluded(self):
        self.assertEqual(
            sum_business_ai_monthly_limits([
                {"spa_id": 1, "monthly_limit_usd": None},
                {"spa_id": 2, "monthly_limit_usd": "2.00"},
            ]),
            Decimal("2.00"),
        )

    def test_duplicate_business_counted_once(self):
        self.assertEqual(
            sum_business_ai_monthly_limits([
                {"spa_id": 1, "monthly_limit_usd": "2.00"},
                {"spa_id": 1, "monthly_limit_usd": "2.00"},
            ]),
            Decimal("2.00"),
        )

    def test_conflicting_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            sum_business_ai_monthly_limits([
                {"spa_id": 1, "monthly_limit_usd": "2.00"},
                {"spa_id": 1, "monthly_limit_usd": "5.00"},
            ])

    def test_dashboard_template_parses(self):
        template = Path(
            "templates/master_admin_ai_financial.html"
        ).read_text()
        Environment().parse(template)
        self.assertIn(
            "Total Business Monthly Limits", template
        )
        self.assertIn(
            "total_business_monthly_limit_usd", template
        )
        self.assertIn(
            'id="aiPlatformMonthlyLimitEditor"', template
        )
        self.assertNotIn(
            "{% if not platform.ai_enabled %}", template
        )
        self.assertNotIn(
            "{% if not business.ai_enabled %}", template
        )


if __name__ == "__main__":
    unittest.main()
