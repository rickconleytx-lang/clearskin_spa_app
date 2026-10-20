"""Coach Peach Assist financial reporting.

Read-only financial summaries for authenticated Master Admin.
Shared by web and Swift API routes.
Caller owns authorization and database connection.
"""

from decimal import Decimal


def _usd(value):
    return format(Decimal(value).quantize(Decimal("0.00000001")), ".8f")


def get_platform_ai_financial_summary(cur):
    """Return the current UTC month's platform AI finances."""

    cur.execute("""
        SELECT date_trunc(
            'month',
            clock_timestamp() AT TIME ZONE 'UTC'
        )::date AS billing_month
    """)
    billing_month = cur.fetchone()["billing_month"]

    cur.execute("""
        SELECT ai_enabled, monthly_limit_usd,
               warning_threshold_percent
        FROM psp_ai_budgets
        WHERE scope = 'platform'
    """)
    budget = cur.fetchone()

    cur.execute("""
        SELECT
            COALESCE(SUM(
                CASE WHEN r.state = 'settled'
                     THEN r.settled_usd ELSE 0 END
            ), 0) AS settled,

            COALESCE(SUM(
                CASE WHEN r.state = 'held'
                     THEN r.reserved_usd ELSE 0 END
            ), 0) AS held,

            COALESCE(SUM(
                CASE WHEN r.state = 'uncertain'
                     THEN r.reserved_usd ELSE 0 END
            ), 0) AS uncertain,

            COUNT(*) FILTER (
                WHERE r.state = 'held'
            ) AS held_count,

            COUNT(*) FILTER (
                WHERE r.state = 'uncertain'
            ) AS uncertain_count,

            COUNT(*) FILTER (
                WHERE u.error_code = 'cost_over_reservation'
                  AND r.state = 'settled'
            ) AS overrun_count

        FROM psp_ai_budget_reservations r
        JOIN psp_ai_usage u
          ON u.ai_usage_id = r.ai_usage_id
        WHERE r.billing_month = %s
    """, (billing_month,))

    totals = cur.fetchone()

    settled = Decimal(totals["settled"])
    held = Decimal(totals["held"])
    uncertain = Decimal(totals["uncertain"])
    committed = settled + held + uncertain

    limit = (
        Decimal(budget["monthly_limit_usd"])
        if budget and budget["monthly_limit_usd"] is not None
        else None
    )

    remaining = (
        max(Decimal("0"), limit - committed)
        if limit is not None else None
    )

    return {
        "billing_month": billing_month.isoformat(),
        "budget_configured": budget is not None,
        "ai_enabled": bool(budget and budget["ai_enabled"]),
        "monthly_limit_usd": (
            _usd(limit) if limit is not None else None
        ),
        "settled_estimated_usd": _usd(settled),
        "held_reservations_usd": _usd(held),
        "uncertain_reservations_usd": _usd(uncertain),
        "committed_estimated_usd": _usd(committed),
        "remaining_usd": (
            _usd(remaining) if remaining is not None else None
        ),
        "held_request_count": int(totals["held_count"]),
        "uncertain_request_count": int(totals["uncertain_count"]),
        "overrun_count": int(totals["overrun_count"]),
        "warning_threshold_percent": (
            budget["warning_threshold_percent"]
            if budget else None
        ),
    }


def get_business_ai_financial_summaries(cur):
    """Read-only UTC monthly AI summary for every PSP business."""

    cur.execute("""
        SELECT date_trunc(
            'month',
            clock_timestamp() AT TIME ZONE 'UTC'
        )::date AS billing_month
    """)
    billing_month = cur.fetchone()["billing_month"]

    cur.execute("""
        SELECT
            s.spa_id,
            s.spa_name,
            s.active,
            b.ai_budget_id,
            b.ai_enabled,
            b.monthly_limit_usd,
            b.warning_threshold_percent,
            COALESCE(t.settled, 0) AS settled,
            COALESCE(t.held, 0) AS held,
            COALESCE(t.uncertain, 0) AS uncertain,
            COALESCE(t.held_count, 0) AS held_count,
            COALESCE(t.uncertain_count, 0) AS uncertain_count,
            COALESCE(t.overrun_count, 0) AS overrun_count
        FROM spas s
        LEFT JOIN psp_ai_budgets b
          ON b.scope = 'business'
         AND b.spa_id = s.spa_id
        LEFT JOIN (
            SELECT
                u.spa_id,
                SUM(r.settled_usd) FILTER (
                    WHERE r.state = 'settled'
                ) AS settled,
                SUM(r.reserved_usd) FILTER (
                    WHERE r.state = 'held'
                ) AS held,
                SUM(r.reserved_usd) FILTER (
                    WHERE r.state = 'uncertain'
                ) AS uncertain,
                COUNT(*) FILTER (
                    WHERE r.state = 'held'
                ) AS held_count,
                COUNT(*) FILTER (
                    WHERE r.state = 'uncertain'
                ) AS uncertain_count,
                COUNT(*) FILTER (
                    WHERE r.state = 'settled'
                      AND u.error_code = 'cost_over_reservation'
                ) AS overrun_count
            FROM psp_ai_usage u
            JOIN psp_ai_budget_reservations r
              ON r.ai_usage_id = u.ai_usage_id
            WHERE r.billing_month = %s
            GROUP BY u.spa_id
        ) t ON t.spa_id = s.spa_id
        ORDER BY s.spa_name NULLS LAST, s.spa_id
    """, (billing_month,))

    businesses = []

    for row in cur.fetchall():
        settled = Decimal(row["settled"])
        held = Decimal(row["held"])
        uncertain = Decimal(row["uncertain"])
        committed = settled + held + uncertain

        limit = (
            Decimal(row["monthly_limit_usd"])
            if row["monthly_limit_usd"] is not None
            else None
        )

        remaining = (
            max(Decimal("0"), limit - committed)
            if limit is not None else None
        )

        businesses.append({
            "spa_id": row["spa_id"],
            "spa_name": row["spa_name"],
            "business_active": bool(row["active"]),
            "budget_configured": row["ai_budget_id"] is not None,
            "ai_enabled": bool(row["ai_enabled"]),
            "monthly_limit_usd": (
                _usd(limit) if limit is not None else None
            ),
            "settled_estimated_usd": _usd(settled),
            "held_reservations_usd": _usd(held),
            "uncertain_reservations_usd": _usd(uncertain),
            "committed_estimated_usd": _usd(committed),
            "remaining_usd": (
                _usd(remaining) if remaining is not None else None
            ),
            "held_request_count": int(row["held_count"]),
            "uncertain_request_count": int(
                row["uncertain_count"]
            ),
            "overrun_count": int(row["overrun_count"]),
            "warning_threshold_percent": (
                row["warning_threshold_percent"]
            ),
        })

    return {
        "billing_month": billing_month.isoformat(),
        "business_count": len(businesses),
        "businesses": businesses,
    }
