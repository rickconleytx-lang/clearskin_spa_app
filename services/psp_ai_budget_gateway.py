"""Coach Peach Assist — internal AI budget reservation service.

Caller owns authorization, transaction, commit, and rollback.
No AI provider calls. No customer-facing endpoints.
"""

from decimal import Decimal, ROUND_UP
from uuid import UUID


class AIBudgetError(ValueError):
    pass


def reserve_ai_request(
    cur, *,
    spa_id,
    business_unit_id,
    actor_user_id,
    request_key,
    feature_key,
    pricing_id,
    max_input_tokens,
    max_output_tokens,
):
    """Atomically reserve text-model spending.

    Requires a RealDictCursor and a caller-owned transaction.
    The caller must commit the hold BEFORE contacting a provider.
    Token caps must be enforced by the future provider gateway.
    """

    for value in (
        spa_id, business_unit_id, actor_user_id, pricing_id
    ):
        if type(value) is not int or value <= 0:
            raise AIBudgetError("Invalid AI request identity.")

    if (
        type(max_input_tokens) is not int
        or not 1 <= max_input_tokens <= 1000000
        or type(max_output_tokens) is not int
        or not 1 <= max_output_tokens <= 32000
    ):
        raise AIBudgetError("Invalid AI token limits.")

    if feature_key not in {
        "help_assist",
        "page_guidance",
        "import_guidance",
        "peachweb_writing",
    }:
        raise AIBudgetError("Unsupported AI feature.")

    try:
        key = str(UUID(str(request_key)))
    except (TypeError, ValueError, AttributeError):
        raise AIBudgetError("Invalid AI request key.") from None

    # Always lock platform first, business second.
    cur.execute("""
        SELECT ai_budget_id, monthly_limit_usd, ai_enabled
        FROM psp_ai_budgets
        WHERE scope = 'platform'
        FOR UPDATE
    """)
    platform = cur.fetchone()

    if not platform or not platform["ai_enabled"]:
        raise AIBudgetError("Platform AI is disabled.")

    cur.execute("""
        SELECT ai_budget_id, monthly_limit_usd, ai_enabled
        FROM psp_ai_budgets
        WHERE scope = 'business' AND spa_id = %s
        FOR UPDATE
    """, (spa_id,))
    business = cur.fetchone()

    if not business or not business["ai_enabled"]:
        raise AIBudgetError("Business AI is disabled.")

    # Duplicate keys must never create additional reservations.
    cur.execute("""
        SELECT ai_usage_id
        FROM psp_ai_usage
        WHERE request_key = %s
    """, (key,))

    if cur.fetchone():
        raise AIBudgetError("AI request already recorded.")

    cur.execute("""
        SELECT
            provider,
            model_name,
            input_usd_per_million_tokens,
            output_usd_per_million_tokens
        FROM psp_ai_model_pricing
        WHERE ai_model_pricing_id = %s
          AND effective_from <= clock_timestamp()
          AND (
              effective_to IS NULL
              OR effective_to > clock_timestamp()
          )
    """, (pricing_id,))
    pricing = cur.fetchone()

    if not pricing:
        raise AIBudgetError("Current AI model pricing unavailable.")

    if pricing["provider"] != "openai":
        raise AIBudgetError("Unsupported AI provider.")

    input_price = Decimal(
        pricing["input_usd_per_million_tokens"]
    )
    output_price = Decimal(
        pricing["output_usd_per_million_tokens"]
    )

    reservation = (
        (
            Decimal(max_input_tokens) * input_price
            + Decimal(max_output_tokens) * output_price
        )
        / Decimal("1000000")
    ).quantize(Decimal("0.00000001"), rounding=ROUND_UP)

    if reservation <= 0:
        raise AIBudgetError("AI reservation must be positive.")

    # Billing months are UTC calendar months.
    cur.execute("""
        SELECT date_trunc(
            'month',
            clock_timestamp() AT TIME ZONE 'UTC'
        )::date AS billing_month
    """)
    billing_month = cur.fetchone()["billing_month"]

    def consumed_usd(business_id=None):
        sql = """
            SELECT COALESCE(SUM(
                CASE
                    WHEN r.state = 'settled'
                        THEN r.settled_usd
                    WHEN r.state IN ('held', 'uncertain')
                        THEN r.reserved_usd
                    ELSE 0
                END
            ), 0) AS consumed
            FROM psp_ai_budget_reservations r
            JOIN psp_ai_usage u
              ON u.ai_usage_id = r.ai_usage_id
            WHERE r.billing_month = %s
        """
        params = [billing_month]

        if business_id is not None:
            sql += " AND u.spa_id = %s"
            params.append(business_id)

        cur.execute(sql, params)
        return Decimal(cur.fetchone()["consumed"])

    for budget, used in (
        (platform, consumed_usd()),
        (business, consumed_usd(spa_id)),
    ):
        limit = budget["monthly_limit_usd"]

        if limit is None:
            raise AIBudgetError("AI spending limit is missing.")

        if used + reservation > Decimal(limit):
            raise AIBudgetError("AI monthly budget exceeded.")

    cur.execute("""
        INSERT INTO psp_ai_usage (
            request_key,
            spa_id,
            business_unit_id,
            requested_by_user_id,
            feature_key,
            provider,
            model_name,
            ai_model_pricing_id,
            status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'reserved')
        RETURNING ai_usage_id
    """, (
        key, spa_id, business_unit_id, actor_user_id,
        feature_key, pricing["provider"],
        pricing["model_name"], pricing_id,
    ))

    usage_id = cur.fetchone()["ai_usage_id"]

    cur.execute("""
        INSERT INTO psp_ai_budget_reservations (
            ai_usage_id,
            billing_month,
            reserved_usd,
            state
        )
        VALUES (%s, %s, %s, 'held')
    """, (usage_id, billing_month, reservation))

    return {
        "ai_usage_id": usage_id,
        "billing_month": billing_month,
        "reserved_usd": reservation,
    }
