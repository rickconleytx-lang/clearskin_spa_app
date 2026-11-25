"""
Peach Suite Pro — saved Stripe billing display snapshots.

Read-only access to previously verified billing information.
No Stripe API calls, billing mutations, or database writes.
"""

from datetime import datetime, timezone

from services.stripe_billing_quote import utc_to_business_time


def _money(cents):
    return f"${cents / 100:,.2f}"


def format_saved_billing_quote(quote, timezone_name="UTC"):
    """Format a previously verified normalized Stripe quote."""

    if not isinstance(quote, dict):
        return None

    if quote.get("stripe_status") not in ("trialing", "active"):
        return None

    if quote.get("billing_interval") not in ("month", "year"):
        return None

    if quote.get("currency") != "usd":
        return None

    base = quote.get("base_cents")
    effective = quote.get("effective_cents")
    discount = quote.get("discount_cents")

    if any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        for value in (base, effective, discount)
    ):
        return None

    if effective > base or base - effective != discount:
        return None

    return {
        "base_display": _money(base),
        "effective_display": _money(effective),
        "discount_display": _money(discount),
        "discount_name": quote.get("discount_name"),
        "has_discount": discount > 0,
        "discount_duration": quote.get("discount_duration"),
        "discount_ends": utc_to_business_time(
            quote.get("discount_ends"),
            timezone_name,
        ),
        "billing_interval": quote["billing_interval"],
        "stripe_status": quote["stripe_status"],
        "next_billing_local": utc_to_business_time(
            quote.get("next_billing_timestamp"),
            timezone_name,
        ),
    }


def load_billing_snapshot(
    cursor,
    *,
    spa_id,
    environment,
    timezone_name="UTC",
):
    """
    Read a saved billing snapshot for the current business.

    Never return pricing attached to an old/replaced
    Stripe subscription.
    """

    environment = str(environment or "").strip().lower()

    if environment not in ("live", "test"):
        raise ValueError("Invalid Stripe environment.")

    cursor.execute(
        """
        SELECT
            a.stripe_subscription_id,
            s.stripe_subscription_id,
            s.quote_json,
            s.verified_at,
            s.invalidated_at,
            s.last_attempt_at,
            s.last_attempt_status
        FROM stripe_billing_accounts a
        LEFT JOIN stripe_billing_display_snapshots s
          ON s.stripe_billing_account_id =
             a.stripe_billing_account_id
         AND s.spa_id = a.spa_id
         AND s.environment = a.environment
        WHERE a.spa_id = %s
          AND a.environment = %s
        LIMIT 1
        """,
        (spa_id, environment),
    )

    row = cursor.fetchone()

    if not row:
        return None

    current_subscription = str(row[0] or "").strip()
    saved_subscription = str(row[1] or "").strip()

    if not current_subscription:
        return None

    # Never display a previous subscription's pricing.
    if saved_subscription and (
        saved_subscription != current_subscription
    ):
        return None

    quote = row[2]
    verified_at = row[3]
    invalidated_at = row[4]
    last_attempt_at = row[5]
    last_attempt_status = row[6]

    details = None

    if verified_at is not None:
        details = format_saved_billing_quote(
            quote,
            timezone_name,
        )

    stale = details is None

    # A time-limited promotion must not silently remain current
    # after its expiration. Preserve the saved quote, but mark it
    # stale until Stripe confirms the current recurring amount.
    if (
        details is not None
        and quote.get("discount_duration") == "repeating"
    ):
        discount_end = utc_to_business_time(
            quote.get("discount_ends"),
            "UTC",
        )

        if (
            discount_end is None
            or discount_end <= datetime.now(timezone.utc)
        ):
            stale = True


    if (
        invalidated_at is not None
        and (
            verified_at is None
            or invalidated_at >= verified_at
        )
    ):
        stale = True

    if (
        last_attempt_status in ("error", "unavailable")
        and last_attempt_at is not None
        and (
            verified_at is None
            or last_attempt_at > verified_at
        )
    ):
        stale = True

    return {
        "billing_details": details,
        "verified_at_local": utc_to_business_time(
            verified_at,
            timezone_name,
        ),
        "last_attempt_at_local": utc_to_business_time(
            last_attempt_at,
            timezone_name,
        ),
        "last_attempt_status": last_attempt_status,
        "is_stale": stale,
    }
