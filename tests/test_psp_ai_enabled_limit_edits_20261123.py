import unittest
from decimal import Decimal
from unittest.mock import patch

from services import psp_ai_platform_control as platform
from services import psp_ai_business_control as business


class PlatformCursor:
    """Mock cursor: records SQL but never connects to PostgreSQL."""

    def __init__(self, current_limit, enabled=True):
        self.rowcount = 0
        self.commands = []
        self.budget = {
            "ai_budget_id": 7,
            "ai_enabled": enabled,
            "monthly_limit_usd": Decimal(current_limit),
        }
        self.next_row = None

    def execute(self, sql, params=None):
        self.commands.append((sql, params))

        if "SELECT" in sql and "FROM psp_ai_budgets" in sql:
            self.next_row = self.budget

        elif "UPDATE psp_ai_budgets" in sql:
            self.rowcount = 1

        elif "INSERT INTO audit_log" in sql:
            self.next_row = {"audit_log_id": 99}

    def fetchone(self):
        return self.next_row


class BusinessCursor:
    """Mock cursor: no actual database access."""

    def __init__(self):
        self.rowcount = 0
        self.commands = []

    def execute(self, sql, params=None):
        self.commands.append((sql, params))

        if "UPDATE psp_ai_budgets" in sql:
            self.rowcount = 1


class EnabledLimitEditTests(unittest.TestCase):

    def test_platform_limit_increase_while_enabled(self):
        cur = PlatformCursor("0.02", enabled=True)

        result = platform.set_platform_ai_monthly_limit(
            cur,
            monthly_limit_usd="5.00",
            expected_limit_usd="0.02",
            actor_user_id=1,
            reason="Increase monthly platform allowance",
        )

        self.assertEqual(result["monthly_limit_usd"], Decimal("5.00"))
        self.assertEqual(result["audit_log_id"], 99)
        self.assertTrue(cur.budget["ai_enabled"])

        updates = [
            sql for sql, _ in cur.commands
            if "UPDATE psp_ai_budgets" in sql
        ]
        self.assertEqual(len(updates), 1)
        self.assertNotIn("ai_enabled", updates[0])

        self.assertTrue(any(
            "INSERT INTO audit_log" in sql
            for sql, _ in cur.commands
        ))

    def test_platform_limit_decrease_while_enabled(self):
        cur = PlatformCursor("5.00", enabled=True)

        result = platform.set_platform_ai_monthly_limit(
            cur,
            monthly_limit_usd="2.00",
            expected_limit_usd="5.00",
            actor_user_id=1,
            reason="Reduce monthly platform allowance",
        )

        self.assertEqual(result["monthly_limit_usd"], Decimal("2.00"))

    def test_platform_stale_value_still_rejected(self):
        cur = PlatformCursor("5.00", enabled=True)

        with self.assertRaises(platform.AIPlatformControlError):
            platform.set_platform_ai_monthly_limit(
                cur,
                monthly_limit_usd="6.00",
                expected_limit_usd="4.00",
                actor_user_id=1,
                reason="Attempt stale platform limit update",
            )

        self.assertFalse(any(
            "UPDATE psp_ai_budgets" in sql
            for sql, _ in cur.commands
        ))

    def test_business_limit_increase_while_enabled(self):
        self.check_business_update("2.00", "3.00", True)

    def test_business_limit_decrease_while_enabled(self):
        self.check_business_update("2.00", "1.00", True)

    def test_disabled_business_still_editable(self):
        self.check_business_update("2.00", "3.00", False)

    def check_business_update(self, old, new, enabled):
        cur = BusinessCursor()

        row = {
            "ai_budget_id": 11,
            "monthly_limit_usd": Decimal(old),
            "ai_enabled": enabled,
        }

        with (
            patch.object(
                business,
                "_lock_business_budget",
                return_value=({"active": True}, row),
            ),
            patch.object(
                business,
                "_write_audit",
                return_value=88,
            ) as audit,
        ):
            result = business.set_business_ai_monthly_limit(
                cur,
                spa_id=41,
                monthly_limit_usd=new,
                expected_limit_usd=old,
                actor_user_id=1,
                reason="Update monthly business allowance",
            )

        self.assertEqual(result["monthly_limit_usd"], Decimal(new))
        self.assertEqual(result["ai_enabled"], enabled)
        self.assertEqual(result["audit_log_id"], 88)
        self.assertTrue(audit.called)

        updates = [
            sql for sql, _ in cur.commands
            if "UPDATE psp_ai_budgets" in sql
        ]

        self.assertEqual(len(updates), 1)
        self.assertNotIn("ai_enabled", updates[0])


if __name__ == "__main__":
    unittest.main()
