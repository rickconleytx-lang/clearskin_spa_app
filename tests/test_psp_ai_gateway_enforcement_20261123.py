import unittest
from datetime import date
from decimal import Decimal
from uuid import UUID

from services import psp_ai_budget_gateway as gateway


MONTH = date(2026, 11, 1)
PRIOR_MONTH = date(2026, 10, 1)


class BudgetCursor:
    """Simulates SQL responses; never connects to PostgreSQL."""

    def __init__(
        self,
        *,
        platform_limit="1.00",
        business_limits=None,
        platform_enabled=True,
        month=MONTH,
    ):
        if business_limits is None:
            business_limits = {
                1: "0.50",
                2: "0.50",
            }

        self.platform = {
            "ai_budget_id": 1,
            "monthly_limit_usd": (
                Decimal(platform_limit)
                if platform_limit is not None else None
            ),
            "ai_enabled": platform_enabled,
        }

        self.businesses = {
            spa_id: {
                "ai_budget_id": spa_id + 10,
                "monthly_limit_usd": (
                    Decimal(amount)
                    if amount is not None else None
                ),
                "ai_enabled": True,
            }
            for spa_id, amount in business_limits.items()
        }

        self.month = month
        self.ledger = []
        self.keys = set()
        self.commands = []
        self._next_row = None
        self._next_usage_id = 100
        self._pending_spa = None

    def add_consumed(
        self,
        spa_id,
        amount,
        *,
        state="settled",
        month=None,
    ):
        self.ledger.append({
            "spa_id": spa_id,
            "month": month or self.month,
            "state": state,
            "reserved_usd": Decimal(amount),
            "settled_usd": Decimal(amount),
        })

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self.commands.append((flat, params))

        if (
            "FROM psp_ai_budgets" in flat
            and "scope = 'platform'" in flat
        ):
            self._next_row = self.platform
            return

        if (
            "FROM psp_ai_budgets" in flat
            and "scope = 'business'" in flat
        ):
            self._next_row = self.businesses.get(params[0])
            return

        if (
            "FROM psp_ai_usage" in flat
            and "WHERE request_key" in flat
        ):
            self._next_row = (
                {"ai_usage_id": 1}
                if params[0] in self.keys
                else None
            )
            return

        if "FROM psp_ai_model_pricing" in flat:
            self._next_row = {
                "provider": "openai",
                "model_name": "synthetic-test-model",
                "input_usd_per_million_tokens": Decimal("1.00"),
                "output_usd_per_million_tokens": Decimal("1.00"),
            }
            return

        if "AS billing_month" in flat:
            self._next_row = {"billing_month": self.month}
            return

        if "FROM psp_ai_budget_reservations r" in flat:
            selected_month = params[0]
            selected_spa = (
                params[1] if len(params) > 1 else None
            )

            total = Decimal("0")

            for entry in self.ledger:
                if entry["month"] != selected_month:
                    continue

                if (
                    selected_spa is not None
                    and entry["spa_id"] != selected_spa
                ):
                    continue

                if entry["state"] == "settled":
                    total += entry["settled_usd"]
                elif entry["state"] in ("held", "uncertain"):
                    total += entry["reserved_usd"]

            self._next_row = {"consumed": total}
            return

        if "INSERT INTO psp_ai_usage" in flat:
            self._next_usage_id += 1
            self._pending_spa = params[1]
            self.keys.add(params[0])
            self._next_row = {
                "ai_usage_id": self._next_usage_id
            }
            return

        if "INSERT INTO psp_ai_budget_reservations" in flat:
            self.ledger.append({
                "spa_id": self._pending_spa,
                "month": params[1],
                "state": "held",
                "reserved_usd": Decimal(params[2]),
                "settled_usd": Decimal("0"),
            })
            self._next_row = None
            return

        raise AssertionError(
            "Unexpected gateway SQL: " + flat[:180]
        )

    def fetchone(self):
        return self._next_row

    def reservation_count(self):
        return sum(
            1
            for sql, _ in self.commands
            if "INSERT INTO psp_ai_budget_reservations" in sql
        )


class GatewayEnforcementTests(unittest.TestCase):

    def setUp(self):
        self.request_number = 0

    def reserve(self, cur, spa_id=1, request_key=None):
        self.request_number += 1

        if request_key is None:
            request_key = str(
                UUID(int=self.request_number)
            )

        return gateway.reserve_ai_request(
            cur,
            spa_id=spa_id,
            business_unit_id=1,
            actor_user_id=1,
            request_key=request_key,
            feature_key="help_assist",
            pricing_id=1,
            max_input_tokens=10000,
            max_output_tokens=10000,
        )

    def test_request_with_available_budget_is_allowed(self):
        cur = BudgetCursor()
        cur.add_consumed(1, "0.10")
        cur.add_consumed(2, "0.20")

        result = self.reserve(cur)

        self.assertEqual(
            result["reserved_usd"],
            Decimal("0.02000000"),
        )
        self.assertEqual(cur.reservation_count(), 1)

    def test_reservation_exactly_at_limit_is_allowed(self):
        cur = BudgetCursor(
            platform_limit="1.00",
            business_limits={1: "1.00"},
        )
        cur.add_consumed(1, "0.98")

        self.reserve(cur)
        self.assertEqual(cur.reservation_count(), 1)

    def test_next_request_over_platform_limit_is_blocked(self):
        cur = BudgetCursor(
            platform_limit="1.00",
            business_limits={1: "2.00"},
        )
        cur.add_consumed(1, "0.99")

        with self.assertRaises(gateway.AIBudgetError):
            self.reserve(cur)

        self.assertEqual(cur.reservation_count(), 0)

    def test_next_request_over_business_limit_is_blocked(self):
        cur = BudgetCursor(
            platform_limit="1.00",
            business_limits={1: "0.20"},
        )
        cur.add_consumed(1, "0.19")

        with self.assertRaises(gateway.AIBudgetError):
            self.reserve(cur)

        self.assertEqual(cur.reservation_count(), 0)

    def test_one_business_exhausted_other_business_allowed(self):
        cur = BudgetCursor(
            platform_limit="1.00",
            business_limits={1: "0.20", 2: "0.20"},
        )
        cur.add_consumed(1, "0.20")

        with self.assertRaises(gateway.AIBudgetError):
            self.reserve(cur, spa_id=1)

        result = self.reserve(cur, spa_id=2)

        self.assertEqual(
            result["reserved_usd"],
            Decimal("0.02000000"),
        )
        self.assertEqual(cur.reservation_count(), 1)

    def test_exhausted_platform_blocks_both_businesses(self):
        cur = BudgetCursor(
            platform_limit="0.40",
            business_limits={1: "1.00", 2: "1.00"},
        )
        cur.add_consumed(1, "0.20")
        cur.add_consumed(2, "0.20")

        for spa_id in (1, 2):
            with self.assertRaises(gateway.AIBudgetError):
                self.reserve(cur, spa_id=spa_id)

        self.assertEqual(cur.reservation_count(), 0)

    def test_increase_platform_limit_restores_access(self):
        cur = BudgetCursor(
            platform_limit="0.40",
            business_limits={1: "1.00"},
        )
        cur.add_consumed(1, "0.40")

        with self.assertRaises(gateway.AIBudgetError):
            self.reserve(cur)

        cur.platform["monthly_limit_usd"] = Decimal("0.50")

        self.reserve(cur)

        self.assertTrue(cur.platform["ai_enabled"])
        self.assertEqual(cur.reservation_count(), 1)

    def test_increase_business_limit_restores_access(self):
        cur = BudgetCursor(
            platform_limit="1.00",
            business_limits={1: "0.20"},
        )
        cur.add_consumed(1, "0.20")

        with self.assertRaises(gateway.AIBudgetError):
            self.reserve(cur)

        cur.businesses[1]["monthly_limit_usd"] = Decimal("0.30")

        self.reserve(cur)

        self.assertTrue(cur.businesses[1]["ai_enabled"])
        self.assertEqual(cur.reservation_count(), 1)

    def test_held_and_uncertain_reservations_count(self):
        cur = BudgetCursor(
            platform_limit="0.30",
            business_limits={1: "0.30"},
        )
        cur.add_consumed(1, "0.14", state="held")
        cur.add_consumed(1, "0.14", state="uncertain")

        self.reserve(cur)

        with self.assertRaises(gateway.AIBudgetError):
            self.reserve(cur)

        self.assertEqual(cur.reservation_count(), 1)

    def test_prior_month_spending_not_charged_to_new_month(self):
        cur = BudgetCursor(
            platform_limit="0.10",
            business_limits={1: "0.10"},
            month=MONTH,
        )
        cur.add_consumed(
            1,
            "0.10",
            month=PRIOR_MONTH,
        )

        self.reserve(cur)
        self.assertEqual(cur.reservation_count(), 1)

    def test_duplicate_request_key_rejected(self):
        cur = BudgetCursor()
        request_key = str(UUID(int=901))

        self.reserve(cur, request_key=request_key)

        with self.assertRaises(gateway.AIBudgetError):
            self.reserve(cur, request_key=request_key)

        self.assertEqual(cur.reservation_count(), 1)

    def test_platform_disabled_blocks_requests(self):
        cur = BudgetCursor(platform_enabled=False)

        with self.assertRaises(gateway.AIBudgetError):
            self.reserve(cur)

        self.assertEqual(cur.reservation_count(), 0)

    def test_business_disabled_blocks_requests(self):
        cur = BudgetCursor()
        cur.businesses[1]["ai_enabled"] = False

        with self.assertRaises(gateway.AIBudgetError):
            self.reserve(cur)

        self.assertEqual(cur.reservation_count(), 0)

    def test_missing_limit_blocks_requests(self):
        cur = BudgetCursor(
            business_limits={1: None},
        )

        with self.assertRaises(gateway.AIBudgetError):
            self.reserve(cur)

        self.assertEqual(cur.reservation_count(), 0)

    def test_platform_locked_before_business(self):
        cur = BudgetCursor()

        self.reserve(cur)

        locks = [
            sql
            for sql, _ in cur.commands
            if "FROM psp_ai_budgets" in sql
            and "FOR UPDATE" in sql
        ]

        self.assertEqual(len(locks), 2)
        self.assertIn("scope = 'platform'", locks[0])
        self.assertIn("scope = 'business'", locks[1])

    def test_reservation_counts_against_next_request(self):
        cur = BudgetCursor(
            platform_limit="0.02",
            business_limits={1: "0.02"},
        )

        self.reserve(cur)

        with self.assertRaises(gateway.AIBudgetError):
            self.reserve(cur)

        self.assertEqual(cur.reservation_count(), 1)


if __name__ == "__main__":
    unittest.main()
