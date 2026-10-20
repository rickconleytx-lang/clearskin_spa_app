"""Coach Peach Assist — AI usage settlement.

Caller owns authorization, transaction, commit and rollback.
No provider calls or external communications.
"""

from decimal import Decimal, ROUND_UP


class AISettlementError(ValueError):
    pass


def settle_ai_request(
    cur, *,
    ai_usage_id,
    input_tokens,
    cached_input_tokens,
    output_tokens,
    provider_request_id=None,
):
    """Settle a submitted or uncertain request using actual usage."""

    if type(ai_usage_id) is not int or ai_usage_id <= 0:
        raise AISettlementError("Invalid AI usage identity.")

    for value in (
        input_tokens, cached_input_tokens, output_tokens
    ):
        if type(value) is not int or value < 0:
            raise AISettlementError("Invalid AI token usage.")

    if cached_input_tokens > input_tokens:
        raise AISettlementError("Invalid cached token count.")

    if provider_request_id is not None:
        if (
            not isinstance(provider_request_id, str)
            or not 1 <= len(provider_request_id) <= 256
        ):
            raise AISettlementError("Invalid provider request ID.")

    cur.execute("""
        SELECT
            u.status,
            r.state AS reservation_state,
            r.reserved_usd,
            p.input_usd_per_million_tokens,
            p.cached_input_usd_per_million_tokens,
            p.output_usd_per_million_tokens
        FROM psp_ai_usage u
        JOIN psp_ai_budget_reservations r
          ON r.ai_usage_id = u.ai_usage_id
        JOIN psp_ai_model_pricing p
          ON p.ai_model_pricing_id = u.ai_model_pricing_id
        WHERE u.ai_usage_id = %s
        FOR UPDATE OF u, r
    """, (ai_usage_id,))

    row = cur.fetchone()

    if not row:
        raise AISettlementError("AI reservation not found.")

    if (
        row["status"] not in ("submitted", "uncertain")
        or row["reservation_state"] not in ("held", "uncertain")
    ):
        raise AISettlementError(
            "AI request cannot be settled in its current state."
        )

    cached_price = row[
        "cached_input_usd_per_million_tokens"
    ]

    if cached_input_tokens and cached_price is None:
        raise AISettlementError(
            "Cached input pricing is unavailable."
        )

    regular_input_tokens = (
        input_tokens - cached_input_tokens
    )

    actual_cost = (
        Decimal(regular_input_tokens)
        * row["input_usd_per_million_tokens"]
        + Decimal(cached_input_tokens)
        * (cached_price if cached_price is not None else Decimal(0))
        + Decimal(output_tokens)
        * row["output_usd_per_million_tokens"]
    ) / Decimal("1000000")

    actual_cost = actual_cost.quantize(
        Decimal("0.00000001"),
        rounding=ROUND_UP,
    )

    # Preserve a durable warning for Master Admin monitoring.
    over_reservation = actual_cost > row["reserved_usd"]

    cur.execute("""
        UPDATE psp_ai_usage
        SET status = 'completed',
            input_tokens = %s,
            cached_input_tokens = %s,
            output_tokens = %s,
            estimated_cost_usd = %s,
            provider_request_id = %s,
            error_code = %s,
            completed_at = clock_timestamp()
        WHERE ai_usage_id = %s
    """, (
        input_tokens,
        cached_input_tokens,
        output_tokens,
        actual_cost,
        provider_request_id,
        "cost_over_reservation" if over_reservation else None,
        ai_usage_id,
    ))

    cur.execute("""
        UPDATE psp_ai_budget_reservations
        SET state = 'settled',
            settled_usd = %s,
            resolved_at = clock_timestamp()
        WHERE ai_usage_id = %s
    """, (actual_cost, ai_usage_id))

    return {
        "ai_usage_id": ai_usage_id,
        "actual_cost_usd": actual_cost,
        "reserved_usd": row["reserved_usd"],
        "over_reservation": over_reservation,
    }
