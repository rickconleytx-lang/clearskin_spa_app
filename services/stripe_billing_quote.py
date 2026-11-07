"""
Read-only Stripe subscription pricing for customer/admin displays.

Only a single fixed-price recurring subscription item with
zero or one fully expanded discount is calculated.

Complex pricing is reported unavailable rather than estimated
incorrectly. No Stripe billing objects are modified.
"""

from decimal import Decimal, ROUND_HALF_UP


def _stripe_to_dict(value):
    """Convert stripe-python 15.x objects to plain dictionaries."""
    if isinstance(value, dict):
        return value

    converter = getattr(value, "to_dict", None)

    if not callable(converter):
        return None

    result = converter()
    return result if isinstance(result, dict) else None


def _cents_after_percent(cents, percent):
    remaining = (
        Decimal(cents)
        * (Decimal("100") - Decimal(str(percent)))
        / Decimal("100")
    )
    return int(
        remaining.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def summarize_stripe_billing(subscription):
    subscription = _stripe_to_dict(subscription)

    if not isinstance(subscription, dict):
        return None

    items = (subscription.get("items") or {}).get("data") or []

    if len(items) != 1:
        return None

    item = items[0]
    price = item.get("price") or {}
    recurring = price.get("recurring") or {}

    interval = recurring.get("interval")
    currency = str(price.get("currency") or "").lower()
    amount = price.get("unit_amount")
    quantity = item.get("quantity", 1)

    if (
        interval not in ("month", "year")
        or recurring.get("interval_count", 1) != 1
        or currency != "usd"
        or not isinstance(amount, int)
        or isinstance(amount, bool)
        or amount < 0
        or not isinstance(quantity, int)
        or isinstance(quantity, bool)
        or quantity < 1
        or recurring.get("usage_type", "licensed") != "licensed"
        or price.get("billing_scheme", "per_unit") != "per_unit"
    ):
        return None

    base_cents = amount * quantity

    # Both modern and legacy Stripe discount representations.
    if "discounts" in subscription:
        subscription_discounts = subscription["discounts"] or []
    elif "discount" in subscription:
        subscription_discounts = (
            [subscription["discount"]]
            if subscription["discount"]
            else []
        )
    else:
        return None

    item_discounts = item.get("discounts") or []

    if not isinstance(subscription_discounts, list):
        return None
    if not isinstance(item_discounts, list):
        return None

    discounts = item_discounts + subscription_discounts

    if len(discounts) > 1:
        return None

    next_charge = (
        subscription.get("trial_end")
        if subscription.get("status") == "trialing"
        else (
            item.get("current_period_end")
            or subscription.get("current_period_end")
        )
    )

    result = {
        "base_cents": base_cents,
        "effective_cents": base_cents,
        "discount_cents": 0,
        "discount_name": None,
        "discount_duration": None,
        "discount_ends": None,
        "billing_interval": interval,
        "currency": currency,
        "next_billing_timestamp": next_charge,
        "stripe_status": subscription.get("status"),
    }

    if not discounts:
        return result

    discount = discounts[0]
    if not isinstance(discount, dict):
        return None

    coupon = discount.get("coupon")
    if not isinstance(coupon, dict):
        source_data = discount.get("source") or {}
        if (
            isinstance(source_data, dict)
            and source_data.get("type") == "coupon"
        ):
            coupon = source_data.get("coupon")

    if not isinstance(coupon, dict):
        return None

    duration = coupon.get("duration")

    # A one-time coupon is not a lasting recurring rate.
    if duration not in ("forever", "repeating"):
        return None

    discount_end = discount.get("end")

    if duration == "repeating":
        if not isinstance(discount_end, int):
            return None

        # A discount expiring before the next charge cannot
        # be represented as the next recurring charge.
        if not isinstance(next_charge, int):
            return None

        if discount_end <= next_charge:
            return result

    percent = coupon.get("percent_off")
    amount_off = coupon.get("amount_off")

    if percent is not None and amount_off is None:
        if not 0 <= Decimal(str(percent)) <= 100:
            return None
        effective = _cents_after_percent(
            base_cents, percent
        )
    elif amount_off is not None and percent is None:
        if (
            not isinstance(amount_off, int)
            or amount_off < 0
            or str(coupon.get("currency") or "").lower()
                != currency
        ):
            return None
        effective = max(0, base_cents - amount_off)
    else:
        return None

    result.update({
        "effective_cents": effective,
        "discount_cents": base_cents - effective,
        "discount_name": (
            coupon.get("name")
            or coupon.get("id")
            or "Stripe promotion"
        ),
        "discount_duration": duration,
        "discount_ends": discount_end,
    })

    return result


def retrieve_stripe_billing_quote(
    subscription_id,
    *,
    environment=None,
):
    """Fetch current Stripe pricing without modifying billing."""
    if not (
        isinstance(subscription_id, str)
        and subscription_id.startswith("sub_")
    ):
        return None

    try:
        import stripe
        from services.stripe_service import (
            get_stripe_environment,
            normalize_stripe_environment,
            get_stripe_secret_key,
        )

        mode = normalize_stripe_environment(
            environment or get_stripe_environment()
        )

        # Dedicated read-only billing client. Never change the
        # global Stripe HTTP client or global retry settings.
        client = stripe.StripeClient(
            get_stripe_secret_key(environment=mode),
            http_client=stripe.RequestsClient(
                timeout=(2.0, 3.0)
            ),
            max_network_retries=0,
        )

        subscription = client.v1.subscriptions.retrieve(
            subscription_id,
            params={
                "expand": [
                    "discounts",
                    "items.data.discounts",
                ],
            },
        )

        subscription = _stripe_to_dict(subscription)
        if subscription is None:
            return None

        if subscription.get("id") != subscription_id:
            return None

        if subscription.get("livemode") is not (
            mode == "live"
        ):
            return None

        # Current Stripe Discount objects may reference a coupon
        # through source.coupon rather than the legacy coupon field.
        # Retrieve only referenced coupons. No billing mutations.
        items = (subscription.get("items") or {}).get("data") or []
        if len(items) != 1:
            return None

        all_discounts = (
            (subscription.get("discounts") or [])
            + (items[0].get("discounts") or [])
        )

        for discount in all_discounts:
            if not isinstance(discount, dict):
                return None

            if isinstance(discount.get("coupon"), dict):
                continue

            source_data = discount.get("source") or {}
            if not isinstance(source_data, dict):
                return None

            if source_data.get("type") != "coupon":
                return None

            coupon_ref = source_data.get("coupon")

            if isinstance(coupon_ref, dict):
                continue

            if not isinstance(coupon_ref, str) or not coupon_ref:
                return None

            coupon = client.v1.coupons.retrieve(coupon_ref)

            coupon = _stripe_to_dict(coupon)
            if coupon is None:
                return None

            if coupon.get("id") != coupon_ref:
                return None

            source_data["coupon"] = coupon

        return summarize_stripe_billing(subscription)

    except Exception:
        # A Stripe outage or unexpected price arrangement
        # must not prevent a PSP page from loading.
        return None


def utc_to_business_time(value, timezone_name):
    """Convert Stripe or database UTC timestamps to business time."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    if value is None:
        return None

    if isinstance(value, int) and not isinstance(value, bool):
        value = datetime.fromtimestamp(value, tz=timezone.utc)

    if not isinstance(value, datetime):
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    try:
        return value.astimezone(ZoneInfo(timezone_name or "UTC"))
    except (KeyError, ValueError):
        return value.astimezone(timezone.utc)


def retrieve_stripe_billing_display(
    subscription_id,
    *,
    timezone_name="UTC",
    environment=None,
):
    """Return display-ready verified Stripe recurring pricing."""
    quote = retrieve_stripe_billing_quote(
        subscription_id,
        environment=environment,
    )

    if not quote or quote.get("stripe_status") not in (
        "trialing", "active"
    ):
        return None

    def money(cents):
        return f"${cents / 100:,.2f}"

    return {
        "base_display": money(quote["base_cents"]),
        "discount_display": money(quote["discount_cents"]),
        "effective_display": money(quote["effective_cents"]),
        "discount_name": quote["discount_name"],
        "has_discount": quote["discount_cents"] > 0,
        "discount_duration": quote["discount_duration"],
        "discount_ends": utc_to_business_time(
            quote["discount_ends"], timezone_name
        ),
        "billing_interval": quote["billing_interval"],
        "next_billing_local": utc_to_business_time(
            quote["next_billing_timestamp"], timezone_name
        ),
        "stripe_status": quote["stripe_status"],
    }
