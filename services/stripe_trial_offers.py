"""Server-controlled trial eligibility for Stripe signups."""

import hmac
import os


STANDARD_TRIAL_DAYS = 10
KATZZ60_TRIAL_DAYS = 60
KATZZ60_OFFER_KEY = "katzz60"
KATZZ60_EMAIL_ENV = "PEACHPOS_KATZZ60_EMAIL"


def resolve_signup_trial_offer(
    *,
    tier_code,
    owner_email,
    submitted_code,
):
    """
    Return the authorized trial and remaining discount code.

    KATZZ60 is a private PeachPOS trial offer, not a Stripe coupon.
    A verified, server-configured email is required for eligibility.
    """
    submitted = str(submitted_code or "").strip()
    tier = str(tier_code or "").strip().lower()
    email = str(owner_email or "").strip().lower()

    is_katzz60 = hmac.compare_digest(
        submitted.lower().encode("utf-8"),
        KATZZ60_OFFER_KEY.encode("utf-8"),
    )

    if not is_katzz60:
        return {
            "trial_period_days": STANDARD_TRIAL_DAYS,
            "trial_offer_key": None,
            "discount_code": submitted,
        }

    allowed_email = os.environ.get(
        KATZZ60_EMAIL_ENV, ""
    ).strip().lower()

    if (
        tier != "pos"
        or not allowed_email
        or not email
        or not hmac.compare_digest(
            email.encode("utf-8"),
            allowed_email.encode("utf-8"),
        )
    ):
        raise ValueError("Discount code is invalid.")

    return {
        "trial_period_days": KATZZ60_TRIAL_DAYS,
        "trial_offer_key": KATZZ60_OFFER_KEY,
        "discount_code": "FFKATZZ",
    }
