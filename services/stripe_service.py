import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import stripe

from services.contact_security import (
    ContactSecurityError,
    normalize_user_mobile_phone,
)
from services.provisioning_service import (
    ProvisioningError,
    provision_new_business_for_owner_invitation,
)


class StripeServiceError(RuntimeError):
    """Raised when a Stripe operation cannot be completed safely."""


STRIPE_ENVIRONMENTS = {
    "test",
    "live",
}


def normalize_stripe_environment(environment):
    """
    Normalize and validate the PSP Stripe environment.

    Defaults to test mode so an unspecified environment can never
    silently become live billing.
    """
    value = str(
        environment or "test"
    ).strip().lower()

    if value not in STRIPE_ENVIRONMENTS:
        raise ValueError(
            "Stripe environment must be 'test' or 'live'."
        )

    return value


def get_stripe_environment():
    return normalize_stripe_environment(
        os.getenv(
            "STRIPE_ENVIRONMENT",
            "test",
        )
    )


def get_stripe_secret_key(
    *,
    environment=None,
):
    """
    Return the configured Stripe secret key while verifying that
    its mode agrees with PSP's configured Stripe environment.
    """
    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    secret_key = os.getenv(
        "STRIPE_SECRET_KEY",
        "",
    ).strip()

    if not secret_key:
        raise ValueError(
            "Missing STRIPE_SECRET_KEY."
        )

    expected_prefix = (
        "sk_test_"
        if environment == "test"
        else "sk_live_"
    )

    if not secret_key.startswith(
        expected_prefix
    ):
        raise ValueError(
            "STRIPE_SECRET_KEY does not match "
            f"Stripe environment '{environment}'."
        )

    return secret_key


def get_stripe_webhook_secret():
    """
    Return the configured Stripe webhook signing secret.

    The signing secret is separate from STRIPE_SECRET_KEY and is
    never returned by diagnostic helpers.
    """
    webhook_secret = os.getenv(
        "STRIPE_WEBHOOK_SECRET",
        "",
    ).strip()

    if not webhook_secret:
        raise ValueError(
            "Missing STRIPE_WEBHOOK_SECRET."
        )

    if not webhook_secret.startswith(
        "whsec_"
    ):
        raise ValueError(
            "STRIPE_WEBHOOK_SECRET is not a valid "
            "Stripe webhook signing secret."
        )

    return webhook_secret


def construct_stripe_webhook_event(
    payload,
    signature_header,
    *,
    environment=None,
):
    """
    Authenticate and validate a Stripe webhook event.

    Signature verification is performed against the configured
    webhook signing secret. The authenticated event's livemode flag
    must also agree with PSP's configured Stripe environment.
    """
    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    signature_header = str(
        signature_header or ""
    ).strip()

    if not signature_header:
        raise StripeServiceError(
            "Missing Stripe webhook signature."
        )

    webhook_secret = get_stripe_webhook_secret()

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=signature_header,
            secret=webhook_secret,
        )

    except (
        ValueError,
        stripe.SignatureVerificationError,
    ) as exc:
        raise StripeServiceError(
            "Stripe webhook signature verification failed."
        ) from exc

    if hasattr(
        event,
        "to_dict_recursive",
    ):
        event = event.to_dict_recursive()
    elif hasattr(
        event,
        "to_dict",
    ):
        event = event.to_dict()
    else:
        event = dict(event)

    expected_livemode = (
        environment == "live"
    )

    actual_livemode = bool(
        event.get("livemode")
    )

    if actual_livemode != expected_livemode:
        raise StripeServiceError(
            "Stripe webhook environment does not match "
            "PSP's configured Stripe environment."
        )

    stripe_event_id = str(
        event.get("id")
        or ""
    ).strip()

    event_type = str(
        event.get("type")
        or ""
    ).strip()

    if not stripe_event_id or not event_type:
        raise StripeServiceError(
            "Stripe webhook event is missing required identity."
        )

    return event


def _stripe_payload_json_default(value):
    """
    Preserve Stripe decimal-formatted values when serializing a
    verified webhook payload for durable JSONB storage.

    stripe-python may expose API fields such as amount_decimal as
    Decimal objects even though Stripe's JSON representation carries
    those decimal values as strings.
    """
    if isinstance(value, Decimal):
        return str(value)

    raise TypeError(
        f"Object of type {type(value).__name__} "
        "is not JSON serializable"
    )


def record_verified_stripe_event(
    cursor,
    event,
    *,
    environment=None,
):
    """
    Idempotently record one signature-verified Stripe event.

    This function records the authenticated event only.
    It does not provision a PSP account or activate a subscription.
    """
    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    if hasattr(event, "to_dict_recursive"):
        payload = event.to_dict_recursive()
    elif hasattr(event, "to_dict"):
        payload = event.to_dict()
    else:
        payload = dict(event)

    stripe_event_id = str(
        payload.get("id")
        or ""
    ).strip()

    event_type = str(
        payload.get("type")
        or ""
    ).strip()

    if not stripe_event_id or not event_type:
        raise StripeServiceError(
            "Stripe webhook event is missing required identity."
        )

    data = payload.get("data") or {}
    stripe_object = data.get("object") or {}

    customer_value = stripe_object.get(
        "customer"
    )
    subscription_value = stripe_object.get(
        "subscription"
    )

    # For customer.subscription.* events, the event object itself
    # is the Subscription, so there is no nested "subscription"
    # field. Preserve that Subscription ID on the durable webhook
    # record just as we do for Checkout/invoice-style objects that
    # carry a subscription reference.
    object_type = str(
        stripe_object.get("object")
        or ""
    ).strip()

    if (
        not subscription_value
        and object_type == "subscription"
    ):
        subscription_value = stripe_object.get(
            "id"
        )

    if isinstance(customer_value, dict):
        customer_value = customer_value.get("id")

    if isinstance(subscription_value, dict):
        subscription_value = subscription_value.get("id")

    stripe_customer_id = str(
        customer_value or ""
    ).strip() or None

    stripe_subscription_id = str(
        subscription_value or ""
    ).strip() or None

    payload_json = json.dumps(
        payload,
        separators=(",", ":"),
        default=_stripe_payload_json_default,
    )

    cursor.execute(
        """
        INSERT INTO stripe_webhook_events (
            environment,
            stripe_event_id,
            event_type,
            stripe_customer_id,
            stripe_subscription_id,
            processing_status,
            payload,
            processing_attempts,
            error_message
        )
        VALUES (
            %s, %s, %s, %s, %s,
            'received', %s::jsonb, 0, NULL
        )
        ON CONFLICT (
            environment,
            stripe_event_id
        )
        DO NOTHING
        RETURNING
            stripe_webhook_event_id,
            processing_status,
            stripe_customer_id,
            stripe_subscription_id,
            spa_id
        """,
        (
            environment,
            stripe_event_id,
            event_type,
            stripe_customer_id,
            stripe_subscription_id,
            payload_json,
        ),
    )

    row = cursor.fetchone()
    duplicate = row is None

    if duplicate:
        cursor.execute(
            """
            SELECT
                stripe_webhook_event_id,
                processing_status,
                stripe_customer_id,
                stripe_subscription_id,
                spa_id
            FROM stripe_webhook_events
            WHERE environment = %s
              AND stripe_event_id = %s
            LIMIT 1
            """,
            (
                environment,
                stripe_event_id,
            ),
        )

        row = cursor.fetchone()

        if not row:
            raise StripeServiceError(
                "Duplicate Stripe webhook event "
                "could not be resolved."
            )

    return {
        "stripe_webhook_event_id": row[0],
        "processing_status": row[1],
        "stripe_customer_id": row[2],
        "stripe_subscription_id": row[3],
        "spa_id": row[4],
        "duplicate": duplicate,
        "event_id": stripe_event_id,
        "event_type": event_type,
    }


def complete_stripe_checkout_signup_from_event(
    cursor,
    event,
    *,
    environment=None,
):
    """
    Validate one authenticated checkout.session.completed event and
    move the exact PSP signup from checkout_created to
    checkout_completed.

    This function does not provision a PSP business, send an owner
    invitation, or activate any add-on.
    """
    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    if hasattr(
        event,
        "to_dict_recursive",
    ):
        payload = event.to_dict_recursive()
    elif hasattr(
        event,
        "to_dict",
    ):
        payload = event.to_dict()
    else:
        payload = dict(event)

    stripe_event_id = str(
        payload.get("id")
        or ""
    ).strip()

    event_type = str(
        payload.get("type")
        or ""
    ).strip()

    if not stripe_event_id:
        raise StripeServiceError(
            "Stripe webhook event ID is missing."
        )

    if event_type != "checkout.session.completed":
        raise StripeServiceError(
            "Stripe webhook event is not a completed "
            "Checkout Session."
        )

    expected_livemode = (
        environment == "live"
    )

    if bool(
        payload.get("livemode")
    ) != expected_livemode:
        raise StripeServiceError(
            "Stripe Checkout completion environment "
            "does not match PSP."
        )

    data = payload.get("data") or {}
    stripe_object = data.get("object") or {}

    if hasattr(
        stripe_object,
        "to_dict_recursive",
    ):
        stripe_object = (
            stripe_object.to_dict_recursive()
        )
    elif hasattr(
        stripe_object,
        "to_dict",
    ):
        stripe_object = stripe_object.to_dict()
    else:
        stripe_object = dict(stripe_object)

    object_type = str(
        stripe_object.get("object")
        or ""
    ).strip()

    if object_type != "checkout.session":
        raise StripeServiceError(
            "Stripe webhook object is not a "
            "Checkout Session."
        )

    checkout_session_id = str(
        stripe_object.get("id")
        or ""
    ).strip()

    if not checkout_session_id:
        raise StripeServiceError(
            "Stripe Checkout Session ID is missing."
        )

    checkout_mode = str(
        stripe_object.get("mode")
        or ""
    ).strip().lower()

    if checkout_mode != "subscription":
        raise StripeServiceError(
            "Stripe Checkout Session is not a "
            "subscription Checkout."
        )

    checkout_status = str(
        stripe_object.get("status")
        or ""
    ).strip().lower()

    if checkout_status != "complete":
        raise StripeServiceError(
            "Stripe Checkout Session is not complete."
        )

    metadata = dict(
        stripe_object.get("metadata")
        or {}
    )

    checkout_signup_token = str(
        metadata.get(
            "psp_checkout_signup_token"
        )
        or ""
    ).strip()

    if not checkout_signup_token:
        raise StripeServiceError(
            "Stripe Checkout Session is missing "
            "the PSP signup token."
        )

    client_reference_id = str(
        stripe_object.get(
            "client_reference_id"
        )
        or ""
    ).strip()

    if (
        client_reference_id
        != checkout_signup_token
    ):
        raise StripeServiceError(
            "Stripe Checkout client reference "
            "does not match PSP signup metadata."
        )

    customer_value = stripe_object.get(
        "customer"
    )

    subscription_value = stripe_object.get(
        "subscription"
    )

    if isinstance(customer_value, dict):
        customer_value = customer_value.get(
            "id"
        )

    if isinstance(
        subscription_value,
        dict,
    ):
        subscription_value = (
            subscription_value.get("id")
        )

    stripe_customer_id = str(
        customer_value or ""
    ).strip()

    stripe_subscription_id = str(
        subscription_value or ""
    ).strip()

    if not stripe_customer_id:
        raise StripeServiceError(
            "Completed Stripe Checkout Session "
            "is missing a customer ID."
        )

    if not stripe_subscription_id:
        raise StripeServiceError(
            "Completed Stripe Checkout Session "
            "is missing a subscription ID."
        )

    # Resolve the signup ONLY through the opaque token supplied in
    # authenticated Stripe metadata. Never resolve by email, name,
    # browser session, or other customer-provided identity.
    cursor.execute(
        """
        SELECT
            stripe_checkout_signup_id,
            signup_status,
            tier_code,
            provider_quantity,
            stripe_checkout_session_id,
            stripe_customer_id,
            stripe_subscription_id,
            checkout_completed_at,
            provisioned_at
        FROM stripe_checkout_signups
        WHERE environment = %s
          AND checkout_signup_token = %s
        FOR UPDATE
        """,
        (
            environment,
            checkout_signup_token,
        ),
    )

    row = cursor.fetchone()

    if not row:
        raise StripeServiceError(
            "Stripe Checkout completion does not "
            "match a PSP signup."
        )

    (
        stripe_checkout_signup_id,
        signup_status,
        tier_code,
        provider_quantity,
        stored_checkout_session_id,
        stored_customer_id,
        stored_subscription_id,
        checkout_completed_at,
        provisioned_at,
    ) = row

    signup_status = str(
        signup_status or ""
    ).strip().lower()

    tier_code = str(
        tier_code or ""
    ).strip().lower()

    stored_checkout_session_id = str(
        stored_checkout_session_id or ""
    ).strip()

    stored_customer_id = str(
        stored_customer_id or ""
    ).strip()

    stored_subscription_id = str(
        stored_subscription_id or ""
    ).strip()

    if tier_code != "solo":
        raise StripeServiceError(
            "Completed Stripe Checkout does not "
            "belong to a Solo signup."
        )

    if int(provider_quantity or 0) != 1:
        raise StripeServiceError(
            "Solo Checkout completion requires "
            "exactly one provider."
        )

    if (
        stored_checkout_session_id
        != checkout_session_id
    ):
        raise StripeServiceError(
            "Completed Stripe Checkout Session "
            "does not match the PSP signup."
        )

    if (
        stored_customer_id
        and stored_customer_id
        != stripe_customer_id
    ):
        raise StripeServiceError(
            "Stripe customer ID conflicts with "
            "the PSP signup."
        )

    if (
        stored_subscription_id
        and stored_subscription_id
        != stripe_subscription_id
    ):
        raise StripeServiceError(
            "Stripe subscription ID conflicts "
            "with the PSP signup."
        )

    # A second Stripe event must never attach one subscription to
    # two PSP signups.
    cursor.execute(
        """
        SELECT
            stripe_checkout_signup_id
        FROM stripe_checkout_signups
        WHERE environment = %s
          AND stripe_subscription_id = %s
          AND stripe_checkout_signup_id <> %s
        LIMIT 1
        """,
        (
            environment,
            stripe_subscription_id,
            stripe_checkout_signup_id,
        ),
    )

    if cursor.fetchone():
        raise StripeServiceError(
            "Stripe subscription is already attached "
            "to another PSP signup."
        )

    # Semantic replay protection. A separately delivered authenticated
    # event for the same completed Checkout Session is safe only when
    # every durable Stripe identity agrees with PSP.
    if signup_status in {
        "checkout_completed",
        "provisioned",
    }:
        if (
            stored_customer_id
            != stripe_customer_id
            or stored_subscription_id
            != stripe_subscription_id
        ):
            raise StripeServiceError(
                "Previously completed PSP signup has "
                "conflicting Stripe identity."
            )

        return {
            "stripe_checkout_signup_id": (
                stripe_checkout_signup_id
            ),
            "signup_status": signup_status,
            "stripe_checkout_session_id": (
                checkout_session_id
            ),
            "stripe_customer_id": (
                stripe_customer_id
            ),
            "stripe_subscription_id": (
                stripe_subscription_id
            ),
            "checkout_completed_at": (
                checkout_completed_at
            ),
            "provisioned_at": provisioned_at,
            "already_completed": True,
            "stripe_event_id": stripe_event_id,
        }

    if signup_status != "checkout_created":
        raise StripeServiceError(
            "PSP signup is not in checkout_created "
            "state."
        )

    cursor.execute(
        """
        UPDATE stripe_checkout_signups
        SET
            signup_status = 'checkout_completed',
            stripe_customer_id = %s,
            stripe_subscription_id = %s,
            checkout_completed_at =
                COALESCE(
                    checkout_completed_at,
                    NOW()
                ),
            updated_at = NOW()
        WHERE stripe_checkout_signup_id = %s
          AND environment = %s
          AND signup_status = 'checkout_created'
          AND stripe_checkout_session_id = %s
          AND (
              stripe_customer_id IS NULL
              OR stripe_customer_id = %s
          )
          AND (
              stripe_subscription_id IS NULL
              OR stripe_subscription_id = %s
          )
        RETURNING
            checkout_completed_at
        """,
        (
            stripe_customer_id,
            stripe_subscription_id,
            stripe_checkout_signup_id,
            environment,
            checkout_session_id,
            stripe_customer_id,
            stripe_subscription_id,
        ),
    )

    updated = cursor.fetchone()

    if not updated:
        raise StripeServiceError(
            "Stripe Checkout completion could not "
            "safely update the PSP signup."
        )

    return {
        "stripe_checkout_signup_id": (
            stripe_checkout_signup_id
        ),
        "signup_status": "checkout_completed",
        "stripe_checkout_session_id": (
            checkout_session_id
        ),
        "stripe_customer_id": (
            stripe_customer_id
        ),
        "stripe_subscription_id": (
            stripe_subscription_id
        ),
        "checkout_completed_at": updated[0],
        "provisioned_at": None,
        "already_completed": False,
        "stripe_event_id": stripe_event_id,
    }


def provision_completed_stripe_signup(
    cursor,
    stripe_checkout_signup_id,
    *,
    environment=None,
):
    """
    Idempotently provision one validated, completed Stripe signup.

    The caller owns the transaction boundary. This function does not
    send the Owner invitation and does not call the Stripe API.
    """
    try:
        signup_id = int(
            stripe_checkout_signup_id
        )
    except (TypeError, ValueError):
        raise StripeServiceError(
            "Stripe checkout signup is invalid."
        )

    if signup_id <= 0:
        raise StripeServiceError(
            "Stripe checkout signup is invalid."
        )

    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    cursor.execute(
        """
        SELECT
            signup_status,
            tier_code,
            provider_quantity,
            business_name,
            owner_first_name,
            owner_last_name,
            owner_email,
            owner_phone,
            timezone_name,
            stripe_checkout_session_id,
            stripe_customer_id,
            stripe_subscription_id,
            checkout_completed_at,
            provisioned_at,
            spa_id
        FROM stripe_checkout_signups
        WHERE stripe_checkout_signup_id = %s
          AND environment = %s
        FOR UPDATE
        """,
        (
            signup_id,
            environment,
        ),
    )

    row = cursor.fetchone()

    if not row:
        raise StripeServiceError(
            "Completed Stripe signup could not be resolved."
        )

    (
        signup_status,
        tier_code,
        provider_quantity,
        business_name,
        owner_first_name,
        owner_last_name,
        owner_email,
        owner_phone,
        timezone_name,
        stripe_checkout_session_id,
        stripe_customer_id,
        stripe_subscription_id,
        checkout_completed_at,
        provisioned_at,
        spa_id,
    ) = row

    signup_status = str(
        signup_status or ""
    ).strip().lower()

    tier_code = str(
        tier_code or ""
    ).strip().lower()

    stripe_checkout_session_id = str(
        stripe_checkout_session_id or ""
    ).strip()

    stripe_customer_id = str(
        stripe_customer_id or ""
    ).strip()

    stripe_subscription_id = str(
        stripe_subscription_id or ""
    ).strip()

    if tier_code != "solo":
        raise StripeServiceError(
            "Only Solo may be provisioned from this "
            "Stripe signup flow."
        )

    if int(provider_quantity or 0) != 1:
        raise StripeServiceError(
            "Solo Stripe provisioning requires "
            "exactly one provider."
        )

    if not stripe_checkout_session_id:
        raise StripeServiceError(
            "Completed Stripe signup is missing its "
            "Checkout Session ID."
        )

    if not stripe_customer_id:
        raise StripeServiceError(
            "Completed Stripe signup is missing its "
            "Stripe customer ID."
        )

    if not stripe_subscription_id:
        raise StripeServiceError(
            "Completed Stripe signup is missing its "
            "Stripe subscription ID."
        )

    if checkout_completed_at is None:
        raise StripeServiceError(
            "Stripe signup has not recorded Checkout completion."
        )

    # If this signup already finished provisioning, treat it as an
    # idempotent replay only when the durable billing relationship
    # still agrees with the signup.
    if signup_status == "provisioned":
        if spa_id is None or provisioned_at is None:
            raise StripeServiceError(
                "Provisioned Stripe signup has incomplete PSP state."
            )

        cursor.execute(
            """
            SELECT
                stripe_billing_account_id,
                stripe_customer_id,
                stripe_subscription_id
            FROM stripe_billing_accounts
            WHERE spa_id = %s
              AND environment = %s
            LIMIT 1
            """,
            (
                spa_id,
                environment,
            ),
        )

        billing_row = cursor.fetchone()

        if not billing_row:
            raise StripeServiceError(
                "Provisioned Stripe signup is missing "
                "its billing account."
            )

        if (
            str(billing_row[1] or "").strip()
            != stripe_customer_id
            or str(billing_row[2] or "").strip()
            != stripe_subscription_id
        ):
            raise StripeServiceError(
                "Provisioned Stripe signup conflicts with "
                "its billing account."
            )

        return {
            "stripe_checkout_signup_id": signup_id,
            "spa_id": spa_id,
            "stripe_billing_account_id": billing_row[0],
            "stripe_customer_id": stripe_customer_id,
            "stripe_subscription_id": stripe_subscription_id,
            "already_provisioned": True,
            "owner_employee_id": None,
            "business_unit_id": None,
            "business_name": business_name,
            "owner_first_name": owner_first_name,
            "owner_last_name": owner_last_name,
            "owner_email": owner_email,
        }

    if signup_status != "checkout_completed":
        raise StripeServiceError(
            "Stripe signup is not ready for provisioning."
        )

    if spa_id is not None or provisioned_at is not None:
        raise StripeServiceError(
            "Unprovisioned Stripe signup already contains "
            "provisioning state."
        )

    # Final duplicate-identity guard before creating any PSP tenant.
    # The database unique indexes remain the race-condition backstop.
    cursor.execute(
        """
        SELECT
            stripe_billing_account_id,
            spa_id,
            stripe_customer_id,
            stripe_subscription_id
        FROM stripe_billing_accounts
        WHERE environment = %s
          AND (
              stripe_customer_id = %s
              OR stripe_subscription_id = %s
          )
        FOR UPDATE
        """,
        (
            environment,
            stripe_customer_id,
            stripe_subscription_id,
        ),
    )

    existing_billing = cursor.fetchone()

    if existing_billing:
        raise StripeServiceError(
            "Stripe customer or subscription is already "
            "attached to another PSP billing account."
        )

    cursor.execute(
        """
        SELECT
            stripe_checkout_signup_id
        FROM stripe_checkout_signups
        WHERE environment = %s
          AND stripe_checkout_signup_id <> %s
          AND (
              stripe_customer_id = %s
              OR stripe_subscription_id = %s
          )
        LIMIT 1
        FOR UPDATE
        """,
        (
            environment,
            signup_id,
            stripe_customer_id,
            stripe_subscription_id,
        ),
    )

    if cursor.fetchone():
        raise StripeServiceError(
            "Stripe customer or subscription is already "
            "attached to another PSP signup."
        )

    try:
        provisioned = (
            provision_new_business_for_owner_invitation(
                cursor,
                business_name=business_name,
                owner_first_name=owner_first_name,
                owner_last_name=owner_last_name,
                owner_email=owner_email,
                subscription_tier_code="solo",
                organization_type_code="solo_owner",
                subscription_status="Trial",
                timezone_name=timezone_name,
                owner_phone=owner_phone or "",
                actor_user_id=None,
            )
        )
    except ProvisioningError as exc:
        raise StripeServiceError(
            "Stripe signup business provisioning failed: "
            f"{exc}"
        ) from exc

    new_spa_id = provisioned["spa_id"]

    cursor.execute(
        """
        INSERT INTO stripe_billing_accounts (
            spa_id,
            environment,
            stripe_customer_id,
            stripe_subscription_id,
            stripe_subscription_status,
            last_synced_at
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            NULL,
            NULL
        )
        RETURNING stripe_billing_account_id
        """,
        (
            new_spa_id,
            environment,
            stripe_customer_id,
            stripe_subscription_id,
        ),
    )

    stripe_billing_account_id = (
        cursor.fetchone()[0]
    )

    cursor.execute(
        """
        UPDATE stripe_checkout_signups
        SET
            signup_status = 'provisioned',
            spa_id = %s,
            provisioned_at =
                COALESCE(
                    provisioned_at,
                    NOW()
                ),
            updated_at = NOW()
        WHERE stripe_checkout_signup_id = %s
          AND environment = %s
          AND signup_status = 'checkout_completed'
          AND spa_id IS NULL
          AND provisioned_at IS NULL
          AND stripe_customer_id = %s
          AND stripe_subscription_id = %s
        RETURNING provisioned_at
        """,
        (
            new_spa_id,
            signup_id,
            environment,
            stripe_customer_id,
            stripe_subscription_id,
        ),
    )

    provisioned_row = cursor.fetchone()

    if not provisioned_row:
        raise StripeServiceError(
            "Stripe signup could not be atomically marked "
            "as provisioned."
        )

    return {
        "stripe_checkout_signup_id": signup_id,
        "spa_id": new_spa_id,
        "stripe_billing_account_id": (
            stripe_billing_account_id
        ),
        "stripe_customer_id": stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
        "already_provisioned": False,
        "owner_employee_id": provisioned[
            "owner_employee_id"
        ],
        "business_unit_id": provisioned[
            "business_unit_id"
        ],
        "business_name": business_name,
        "owner_first_name": owner_first_name,
        "owner_last_name": owner_last_name,
        "owner_email": owner_email,
    }


def process_recorded_stripe_webhook_event(
    cursor,
    stripe_webhook_event_id,
    *,
    environment=None,
):
    """
    Process one already-authenticated, durably recorded Stripe event.

    The durable stripe_webhook_events payload is the processing source
    of truth. Completed Checkout events may provision the PSP business,
    but this function never sends the Owner invitation or commits.
    """
    try:
        webhook_event_id = int(
            stripe_webhook_event_id
        )
    except (TypeError, ValueError):
        raise StripeServiceError(
            "Stripe webhook event record is invalid."
        )

    if webhook_event_id <= 0:
        raise StripeServiceError(
            "Stripe webhook event record is invalid."
        )

    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    cursor.execute(
        """
        SELECT
            stripe_event_id,
            event_type,
            processing_status,
            payload,
            processing_attempts
        FROM stripe_webhook_events
        WHERE stripe_webhook_event_id = %s
          AND environment = %s
        FOR UPDATE
        """,
        (
            webhook_event_id,
            environment,
        ),
    )

    row = cursor.fetchone()

    if not row:
        raise StripeServiceError(
            "Recorded Stripe webhook event "
            "could not be resolved."
        )

    (
        stored_stripe_event_id,
        stored_event_type,
        processing_status,
        payload,
        processing_attempts,
    ) = row

    stored_stripe_event_id = str(
        stored_stripe_event_id or ""
    ).strip()

    stored_event_type = str(
        stored_event_type or ""
    ).strip()

    processing_status = str(
        processing_status or ""
    ).strip().lower()

    if processing_status in {
        "processed",
        "ignored",
    }:
        return {
            "stripe_webhook_event_id": webhook_event_id,
            "stripe_event_id": stored_stripe_event_id,
            "event_type": stored_event_type,
            "processing_status": processing_status,
            "processing_attempts": int(
                processing_attempts or 0
            ),
            "already_final": True,
            "signup_completion": None,
        }

    if processing_status not in {
        "received",
        "processing",
        "error",
    }:
        raise StripeServiceError(
            "Stripe webhook event has an "
            "unsupported processing state."
        )

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise StripeServiceError(
                "Recorded Stripe webhook payload "
                "is invalid JSON."
            ) from exc

    if not isinstance(payload, dict):
        raise StripeServiceError(
            "Recorded Stripe webhook payload "
            "is invalid."
        )

    payload_event_id = str(
        payload.get("id")
        or ""
    ).strip()

    payload_event_type = str(
        payload.get("type")
        or ""
    ).strip()

    if (
        not payload_event_id
        or payload_event_id
        != stored_stripe_event_id
    ):
        raise StripeServiceError(
            "Recorded Stripe webhook event ID "
            "does not match its payload."
        )

    if (
        not payload_event_type
        or payload_event_type
        != stored_event_type
    ):
        raise StripeServiceError(
            "Recorded Stripe webhook event type "
            "does not match its payload."
        )

    if "livemode" not in payload:
        raise StripeServiceError(
            "Recorded Stripe webhook payload "
            "is missing its environment."
        )

    expected_livemode = (
        environment == "live"
    )

    if bool(
        payload.get("livemode")
    ) != expected_livemode:
        raise StripeServiceError(
            "Recorded Stripe webhook environment "
            "does not match PSP."
        )

    cursor.execute(
        """
        UPDATE stripe_webhook_events
        SET
            processing_status = 'processing',
            processing_attempts =
                processing_attempts + 1,
            error_message = NULL,
            processed_at = NULL
        WHERE stripe_webhook_event_id = %s
          AND environment = %s
        RETURNING processing_attempts
        """,
        (
            webhook_event_id,
            environment,
        ),
    )

    attempt_row = cursor.fetchone()

    if not attempt_row:
        raise StripeServiceError(
            "Stripe webhook event could not "
            "enter processing state."
        )

    processing_attempts = int(
        attempt_row[0]
    )

    cursor.execute(
        "SAVEPOINT stripe_webhook_processing"
    )

    try:
        signup_completion = None
        provisioning_result = None
        subscription_sync = None

        if (
            stored_event_type
            == "checkout.session.completed"
        ):
            signup_completion = (
                complete_stripe_checkout_signup_from_event(
                    cursor,
                    payload,
                    environment=environment,
                )
            )

            provisioning_result = (
                provision_completed_stripe_signup(
                    cursor,
                    signup_completion[
                        "stripe_checkout_signup_id"
                    ],
                    environment=environment,
                )
            )

            cursor.execute(
                """
                UPDATE stripe_webhook_events
                SET
                    processing_status = 'processed',
                    stripe_customer_id = %s,
                    stripe_subscription_id = %s,
                    stripe_billing_account_id = %s,
                    spa_id = %s,
                    error_message = NULL,
                    processed_at = NOW()
                WHERE stripe_webhook_event_id = %s
                  AND environment = %s
                """,
                (
                    signup_completion[
                        "stripe_customer_id"
                    ],
                    signup_completion[
                        "stripe_subscription_id"
                    ],
                    provisioning_result[
                        "stripe_billing_account_id"
                    ],
                    provisioning_result["spa_id"],
                    webhook_event_id,
                    environment,
                ),
            )

            final_status = "processed"

        elif (
            stored_event_type
            in STRIPE_SUBSCRIPTION_LIFECYCLE_EVENT_TYPES
        ):
            subscription_sync = (
                sync_stripe_subscription_from_event(
                    cursor,
                    payload,
                    environment=environment,
                )
            )

            cursor.execute(
                """
                UPDATE stripe_webhook_events
                SET
                    processing_status = 'processed',
                    stripe_customer_id = %s,
                    stripe_subscription_id = %s,
                    stripe_billing_account_id = %s,
                    spa_id = %s,
                    error_message = NULL,
                    processed_at = NOW()
                WHERE stripe_webhook_event_id = %s
                  AND environment = %s
                """,
                (
                    subscription_sync[
                        "stripe_customer_id"
                    ],
                    subscription_sync[
                        "stripe_subscription_id"
                    ],
                    subscription_sync[
                        "stripe_billing_account_id"
                    ],
                    subscription_sync["spa_id"],
                    webhook_event_id,
                    environment,
                ),
            )

            final_status = "processed"

        else:
            # Authenticated Stripe event type is not handled yet.
            # Preserve it durably and acknowledge it without changing
            # any PSP signup or subscription state.
            cursor.execute(
                """
                UPDATE stripe_webhook_events
                SET
                    processing_status = 'ignored',
                    error_message = NULL,
                    processed_at = NOW()
                WHERE stripe_webhook_event_id = %s
                  AND environment = %s
                """,
                (
                    webhook_event_id,
                    environment,
                ),
            )

            final_status = "ignored"

        cursor.execute(
            "RELEASE SAVEPOINT stripe_webhook_processing"
        )

        return {
            "stripe_webhook_event_id": webhook_event_id,
            "stripe_event_id": stored_stripe_event_id,
            "event_type": stored_event_type,
            "processing_status": final_status,
            "processing_attempts": processing_attempts,
            "already_final": False,
            "signup_completion": signup_completion,
            "provisioning_result": provisioning_result,
            "subscription_sync": subscription_sync,
        }

    except Exception as exc:
        # Recover the transaction even if a database statement inside
        # event processing failed, then preserve a durable error state.
        cursor.execute(
            "ROLLBACK TO SAVEPOINT stripe_webhook_processing"
        )
        cursor.execute(
            "RELEASE SAVEPOINT stripe_webhook_processing"
        )

        error_message = str(
            exc
        ).strip()

        if not error_message:
            error_message = (
                exc.__class__.__name__
            )

        error_message = error_message[:2000]

        cursor.execute(
            """
            UPDATE stripe_webhook_events
            SET
                processing_status = 'error',
                error_message = %s,
                processed_at = NULL
            WHERE stripe_webhook_event_id = %s
              AND environment = %s
            """,
            (
                error_message,
                webhook_event_id,
                environment,
            ),
        )

        return {
            "stripe_webhook_event_id": webhook_event_id,
            "stripe_event_id": stored_stripe_event_id,
            "event_type": stored_event_type,
            "processing_status": "error",
            "processing_attempts": processing_attempts,
            "already_final": False,
            "signup_completion": None,
            "error_message": error_message,
        }


def configure_stripe(
    *,
    environment=None,
):
    """
    Configure stripe-python for the requested PSP environment.

    Returns the normalized environment. The secret key itself is
    intentionally never returned to callers that only need to know
    which mode is active.
    """
    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    stripe.api_key = get_stripe_secret_key(
        environment=environment
    )

    return environment


def stripe_configuration_summary():
    """
    Return non-secret Stripe configuration information suitable
    for diagnostics and Master Admin health checks.
    """
    environment = get_stripe_environment()

    try:
        get_stripe_secret_key(
            environment=environment
        )
        configured = True
    except ValueError:
        configured = False

    return {
        "environment": environment,
        "secret_key_configured": configured,
    }

STRIPE_BILLING_INTERVALS = {
    "month",
    "year",
}

LAUNCH10_CODE = "LAUNCH10"

LAUNCH10_CUTOFF_LOCAL = datetime(
    2026,
    12,
    31,
    23,
    59,
    59,
    tzinfo=ZoneInfo("America/Chicago"),
)


def normalize_stripe_billing_interval(
    billing_interval,
):
    value = str(
        billing_interval or ""
    ).strip().lower()

    if value not in STRIPE_BILLING_INTERVALS:
        raise ValueError(
            "Billing interval must be 'month' or 'year'."
        )

    return value


def _normalized_discount_code(value):
    return str(
        value or ""
    ).strip().upper()


def _friends_family_code():
    code = str(
        os.getenv(
            "PSP_FRIENDS_FAMILY_CODE",
            "",
        )
        or ""
    ).strip()

    if not code:
        raise ValueError(
            "Friends/Family discount configuration is missing."
        )

    return code


def _normalize_aware_datetime(value):
    if value is None:
        return datetime.now(
            timezone.utc
        )

    if not isinstance(value, datetime):
        raise ValueError(
            "Discount validation time must be a datetime."
        )

    if value.tzinfo is None:
        raise ValueError(
            "Discount validation time must include a timezone."
        )

    return value


def validate_subscription_discount_code(
    submitted_code,
    *,
    now=None,
):
    """
    Validate a customer-entered PSP subscription discount code.

    Returns:
        None
        "launch10"
        "friends_family"

    The private Friends/Family code is read only from environment
    configuration and is never returned, persisted, or logged.
    """
    normalized_code = _normalized_discount_code(
        submitted_code
    )

    if not normalized_code:
        return None

    validation_time = (
        _normalize_aware_datetime(now)
    )

    if hmac.compare_digest(
        normalized_code,
        LAUNCH10_CODE,
    ):
        cutoff_utc = (
            LAUNCH10_CUTOFF_LOCAL
            .astimezone(timezone.utc)
        )

        if (
            validation_time
            .astimezone(timezone.utc)
            > cutoff_utc
        ):
            raise ValueError(
                "LAUNCH10 is no longer available."
            )

        return "launch10"

    expected_friends_family = (
        _normalized_discount_code(
            _friends_family_code()
        )
    )

    if hmac.compare_digest(
        normalized_code,
        expected_friends_family,
    ):
        return "friends_family"

    raise ValueError(
        "Discount code is invalid."
    )


def get_stripe_discount_mapping(
    cursor,
    *,
    discount_key,
    tier_code,
    billing_interval,
    environment=None,
    now=None,
):
    """
    Return the active PSP-to-Stripe coupon mapping for one
    validated discount.

    The caller must validate the customer-entered code first.
    """
    discount_key = str(
        discount_key or ""
    ).strip().lower()

    if discount_key not in {
        "launch10",
        "friends_family",
    }:
        raise ValueError(
            "Unsupported Stripe discount key."
        )

    tier_code = str(
        tier_code or ""
    ).strip().lower()

    if not tier_code:
        raise ValueError(
            "Subscription tier is required."
        )

    billing_interval = (
        normalize_stripe_billing_interval(
            billing_interval
        )
    )

    environment = (
        normalize_stripe_environment(
            environment
            or get_stripe_environment()
        )
    )

    lookup_time = (
        _normalize_aware_datetime(now)
    )

    cursor.execute(
        """
        SELECT
            stripe_discount_catalog_id,
            stripe_coupon_id,
            discount_type,
            percent_off,
            amount_off_cents,
            currency,
            valid_through
        FROM stripe_discount_catalog
        WHERE environment = %s
          AND discount_key = %s
          AND tier_code = %s
          AND billing_interval = %s
          AND is_active = TRUE
          AND (
              valid_through IS NULL
              OR valid_through >= %s
          )
        LIMIT 2
        """,
        (
            environment,
            discount_key,
            tier_code,
            billing_interval,
            lookup_time,
        ),
    )

    rows = cursor.fetchall()

    if not rows:
        raise StripeServiceError(
            "No active Stripe discount mapping is available."
        )

    if len(rows) != 1:
        raise StripeServiceError(
            "Multiple active Stripe discount mappings were found."
        )

    row = rows[0]

    return {
        "stripe_discount_catalog_id": row[0],
        "stripe_coupon_id": row[1],
        "discount_type": row[2],
        "percent_off": row[3],
        "amount_off_cents": row[4],
        "currency": row[5],
        "valid_through": row[6],
        "discount_key": discount_key,
        "tier_code": tier_code,
        "billing_interval": billing_interval,
        "environment": environment,
    }

STRIPE_PRICE_ITEM_KINDS = {
    "base_plan",
    "sms_addon",
}


def get_stripe_price_mapping(
    cursor,
    *,
    item_kind,
    billing_interval,
    tier_code=None,
    environment=None,
):
    """
    Return one active PSP-to-Stripe Product/Price mapping.

    Base-plan lookups require a tier code.
    Platform add-ons must not supply a tier code.
    """
    item_kind = str(
        item_kind or ""
    ).strip().lower()

    if item_kind not in STRIPE_PRICE_ITEM_KINDS:
        raise ValueError(
            "Unsupported Stripe price item kind."
        )

    normalized_interval = (
        normalize_stripe_billing_interval(
            billing_interval
        )
    )

    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    normalized_tier = str(
        tier_code or ""
    ).strip().lower()

    if item_kind == "base_plan":
        if not normalized_tier:
            raise ValueError(
                "Subscription tier is required "
                "for a base-plan price."
            )

        tier_clause = "tier_code = %s"
        tier_params = [normalized_tier]

    else:
        if normalized_tier:
            raise ValueError(
                "Stripe add-on prices do not use a tier code."
            )

        tier_clause = "tier_code IS NULL"
        tier_params = []

    cursor.execute(
        f"""
        SELECT
            stripe_price_catalog_id,
            stripe_product_id,
            stripe_price_id,
            unit_amount_cents,
            currency
        FROM stripe_price_catalog
        WHERE environment = %s
          AND item_kind = %s
          AND {tier_clause}
          AND billing_interval = %s
          AND is_active = TRUE
        LIMIT 2
        """,
        (
            environment,
            item_kind,
            *tier_params,
            normalized_interval,
        ),
    )

    rows = cursor.fetchall()

    if not rows:
        raise StripeServiceError(
            "No active Stripe price mapping is available."
        )

    if len(rows) != 1:
        raise StripeServiceError(
            "Multiple active Stripe price mappings were found."
        )

    row = rows[0]

    return {
        "stripe_price_catalog_id": row[0],
        "stripe_product_id": row[1],
        "stripe_price_id": row[2],
        "unit_amount_cents": row[3],
        "currency": row[4],
        "item_kind": item_kind,
        "tier_code": (
            normalized_tier
            if item_kind == "base_plan"
            else None
        ),
        "billing_interval": normalized_interval,
        "environment": environment,
    }




def get_stripe_price_mapping_by_price_id(
    cursor,
    *,
    stripe_price_id,
    environment=None,
):
    """
    Resolve one active Stripe subscription Price back to PSP's
    authoritative catalog mapping.

    This reverse lookup is used when processing Stripe subscription
    lifecycle events. Only recurring PSP subscription items are valid
    here; one-time services such as 10DLC assistance are intentionally
    excluded.
    """
    stripe_price_id = str(
        stripe_price_id or ""
    ).strip()

    if not stripe_price_id:
        raise StripeServiceError(
            "Stripe subscription item Price ID is missing."
        )

    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    cursor.execute(
        """
        SELECT
            stripe_price_catalog_id,
            item_kind,
            tier_code,
            billing_interval,
            stripe_product_id,
            stripe_price_id,
            unit_amount_cents,
            currency
        FROM stripe_price_catalog
        WHERE environment = %s
          AND stripe_price_id = %s
          AND item_kind IN (
              'base_plan',
              'sms_addon'
          )
        LIMIT 2
        """,
        (
            environment,
            stripe_price_id,
        ),
    )

    rows = cursor.fetchall()

    if not rows:
        raise StripeServiceError(
            "Stripe subscription Price is not mapped "
            "to a PSP subscription item."
        )

    if len(rows) != 1:
        raise StripeServiceError(
            "Stripe subscription Price has multiple "
            "PSP catalog mappings."
        )

    row = rows[0]

    return {
        "stripe_price_catalog_id": row[0],
        "item_kind": row[1],
        "tier_code": row[2],
        "billing_interval": row[3],
        "stripe_product_id": row[4],
        "stripe_price_id": row[5],
        "unit_amount_cents": row[6],
        "currency": row[7],
        "environment": environment,
    }



def _stripe_unix_timestamp_to_datetime(
    value,
    *,
    field_name,
):
    """
    Convert one Stripe Unix timestamp to an aware UTC datetime.
    Stripe nullable lifecycle timestamps remain None.
    """
    if value is None:
        return None

    if isinstance(value, bool):
        raise StripeServiceError(
            f"Stripe {field_name} timestamp is invalid."
        )

    try:
        timestamp_value = int(value)
    except (TypeError, ValueError) as exc:
        raise StripeServiceError(
            f"Stripe {field_name} timestamp is invalid."
        ) from exc

    if timestamp_value < 0:
        raise StripeServiceError(
            f"Stripe {field_name} timestamp is invalid."
        )

    try:
        return datetime.fromtimestamp(
            timestamp_value,
            tz=timezone.utc,
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise StripeServiceError(
            f"Stripe {field_name} timestamp is invalid."
        ) from exc


def sync_stripe_subscription_snapshot(
    cursor,
    subscription,
    *,
    environment=None,
):
    """
    Synchronize one Stripe Subscription object into PSP's durable
    billing-account and subscription-item tables.

    The Stripe subscription/customer identities must already belong
    to a PSP billing account. Incoming Price IDs are resolved through
    PSP's known Stripe price catalog before any item is accepted.

    The caller owns the database transaction.
    """
    if hasattr(subscription, "to_dict"):
        subscription = subscription.to_dict()

    if not isinstance(subscription, dict):
        raise StripeServiceError(
            "Stripe Subscription payload is invalid."
        )

    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    expected_livemode = (
        environment == "live"
    )

    if "livemode" not in subscription:
        raise StripeServiceError(
            "Stripe Subscription environment is missing."
        )

    if bool(
        subscription.get("livemode")
    ) != expected_livemode:
        raise StripeServiceError(
            "Stripe Subscription environment does not match PSP."
        )

    subscription_id = str(
        subscription.get("id")
        or ""
    ).strip()

    customer_value = subscription.get("customer")

    if isinstance(customer_value, dict):
        customer_id = str(
            customer_value.get("id")
            or ""
        ).strip()
    else:
        customer_id = str(
            customer_value
            or ""
        ).strip()

    subscription_status = str(
        subscription.get("status")
        or ""
    ).strip().lower()

    if not subscription_id:
        raise StripeServiceError(
            "Stripe Subscription ID is missing."
        )

    if not customer_id:
        raise StripeServiceError(
            "Stripe Subscription customer ID is missing."
        )

    if (
        not subscription_status
        or len(subscription_status) > 40
    ):
        raise StripeServiceError(
            "Stripe Subscription status is invalid."
        )

    trial_start = _stripe_unix_timestamp_to_datetime(
        subscription.get("trial_start"),
        field_name="trial_start",
    )

    trial_end = _stripe_unix_timestamp_to_datetime(
        subscription.get("trial_end"),
        field_name="trial_end",
    )

    cancel_at = _stripe_unix_timestamp_to_datetime(
        subscription.get("cancel_at"),
        field_name="cancel_at",
    )

    canceled_at = _stripe_unix_timestamp_to_datetime(
        subscription.get("canceled_at"),
        field_name="canceled_at",
    )

    ended_at = _stripe_unix_timestamp_to_datetime(
        subscription.get("ended_at"),
        field_name="ended_at",
    )

    cancel_at_period_end_value = subscription.get(
        "cancel_at_period_end"
    )

    if not isinstance(
        cancel_at_period_end_value,
        bool,
    ):
        raise StripeServiceError(
            "Stripe Subscription cancel-at-period-end "
            "value is invalid."
        )

    cancel_at_period_end = cancel_at_period_end_value

    cursor.execute(
        """
        SELECT
            a.stripe_billing_account_id,
            a.spa_id,
            a.stripe_customer_id,
            st.tier_code
        FROM stripe_billing_accounts a
        JOIN spas s
          ON s.spa_id = a.spa_id
        JOIN subscription_tiers st
          ON st.subscription_tier_id =
             s.subscription_tier_id
        WHERE a.environment = %s
          AND a.stripe_subscription_id = %s
        FOR UPDATE OF a
        """,
        (
            environment,
            subscription_id,
        ),
    )

    billing_row = cursor.fetchone()

    if not billing_row:
        raise StripeServiceError(
            "Stripe Subscription is not linked to a PSP "
            "billing account."
        )

    (
        stripe_billing_account_id,
        spa_id,
        stored_customer_id,
        spa_tier_code,
    ) = billing_row

    spa_tier_code = str(
        spa_tier_code or ""
    ).strip().lower()

    if not spa_tier_code:
        raise StripeServiceError(
            "PSP business subscription tier could not be resolved."
        )

    if str(
        stored_customer_id or ""
    ).strip() != customer_id:
        raise StripeServiceError(
            "Stripe Subscription customer does not match "
            "the PSP billing account."
        )

    items_container = (
        subscription.get("items")
        or {}
    )

    if not isinstance(items_container, dict):
        raise StripeServiceError(
            "Stripe Subscription items payload is invalid."
        )

    if items_container.get("has_more") is True:
        raise StripeServiceError(
            "Stripe Subscription items payload is incomplete."
        )

    subscription_items = (
        items_container.get("data")
        or []
    )

    if not isinstance(subscription_items, list):
        raise StripeServiceError(
            "Stripe Subscription items payload is invalid."
        )

    if not subscription_items:
        raise StripeServiceError(
            "Stripe Subscription has no subscription items."
        )

    seen_item_ids = set()
    seen_item_kinds = set()
    synchronized_item_ids = []

    # A canceled or expired incomplete Subscription no longer has
    # active PSP billing items, even though Stripe may still include
    # the historical item objects in the Subscription snapshot.
    items_should_be_active = subscription_status not in {
        "canceled",
        "incomplete_expired",
    }

    # Retire the previous active snapshot before applying the new one.
    # This prevents a plan/item replacement from colliding with the
    # one-active-base-plan / one-active-SMS-item uniqueness guards.
    # Any later validation failure rolls back with the surrounding
    # transaction/savepoint.
    cursor.execute(
        """
        UPDATE stripe_subscription_items
        SET
            is_active = FALSE,
            updated_at = NOW()
        WHERE stripe_billing_account_id = %s
          AND environment = %s
          AND is_active = TRUE
        """,
        (
            stripe_billing_account_id,
            environment,
        ),
    )

    for item in subscription_items:
        if not isinstance(item, dict):
            raise StripeServiceError(
                "Stripe Subscription item is invalid."
            )

        stripe_item_id = str(
            item.get("id")
            or ""
        ).strip()

        if not stripe_item_id:
            raise StripeServiceError(
                "Stripe Subscription item ID is missing."
            )

        if stripe_item_id in seen_item_ids:
            raise StripeServiceError(
                "Stripe Subscription contains a duplicate item ID."
            )

        seen_item_ids.add(
            stripe_item_id
        )

        price = item.get("price") or {}

        if not isinstance(price, dict):
            raise StripeServiceError(
                "Stripe Subscription item Price is invalid."
            )

        stripe_price_id = str(
            price.get("id")
            or ""
        ).strip()

        mapping = get_stripe_price_mapping_by_price_id(
            cursor,
            stripe_price_id=stripe_price_id,
            environment=environment,
        )

        item_kind = mapping["item_kind"]

        if item_kind == "base_plan":
            mapped_tier_code = str(
                mapping["tier_code"]
                or ""
            ).strip().lower()

            if (
                not mapped_tier_code
                or mapped_tier_code != spa_tier_code
            ):
                raise StripeServiceError(
                    "Stripe base-plan price does not match "
                    "the PSP business subscription tier."
                )

        if item_kind in seen_item_kinds:
            raise StripeServiceError(
                "Stripe Subscription contains multiple active "
                f"{item_kind} items."
            )

        seen_item_kinds.add(
            item_kind
        )

        product_value = price.get("product")

        if isinstance(product_value, dict):
            stripe_product_id = str(
                product_value.get("id")
                or ""
            ).strip()
        else:
            stripe_product_id = str(
                product_value
                or ""
            ).strip()

        if (
            not stripe_product_id
            or stripe_product_id
            != str(
                mapping["stripe_product_id"]
                or ""
            ).strip()
        ):
            raise StripeServiceError(
                "Stripe Subscription item Product does not "
                "match PSP's price catalog."
            )

        try:
            quantity = int(
                item.get("quantity")
                or 0
            )
        except (TypeError, ValueError) as exc:
            raise StripeServiceError(
                "Stripe Subscription item quantity is invalid."
            ) from exc

        if quantity <= 0:
            raise StripeServiceError(
                "Stripe Subscription item quantity is invalid."
            )

        current_period_start = (
            _stripe_unix_timestamp_to_datetime(
                item.get("current_period_start"),
                field_name="current_period_start",
            )
        )

        current_period_end = (
            _stripe_unix_timestamp_to_datetime(
                item.get("current_period_end"),
                field_name="current_period_end",
            )
        )

        cursor.execute(
            """
            SELECT
                stripe_subscription_item_id,
                stripe_billing_account_id,
                spa_id
            FROM stripe_subscription_items
            WHERE environment = %s
              AND stripe_item_id = %s
            FOR UPDATE
            """,
            (
                environment,
                stripe_item_id,
            ),
        )

        existing_item = cursor.fetchone()

        if existing_item:
            if (
                existing_item[1]
                != stripe_billing_account_id
                or existing_item[2] != spa_id
            ):
                raise StripeServiceError(
                    "Stripe Subscription item is already linked "
                    "to another PSP billing account."
                )

            cursor.execute(
                """
                UPDATE stripe_subscription_items
                SET
                    item_kind = %s,
                    stripe_product_id = %s,
                    stripe_price_id = %s,
                    billing_interval = %s,
                    quantity = %s,
                    unit_amount_cents = %s,
                    currency = %s,
                    current_period_start = %s,
                    current_period_end = %s,
                    is_active = %s,
                    updated_at = NOW()
                WHERE stripe_subscription_item_id = %s
                """,
                (
                    item_kind,
                    mapping["stripe_product_id"],
                    mapping["stripe_price_id"],
                    mapping["billing_interval"],
                    quantity,
                    mapping["unit_amount_cents"],
                    mapping["currency"],
                    current_period_start,
                    current_period_end,
                    items_should_be_active,
                    existing_item[0],
                ),
            )

        else:
            cursor.execute(
                """
                INSERT INTO stripe_subscription_items (
                    stripe_billing_account_id,
                    spa_id,
                    environment,
                    item_kind,
                    stripe_item_id,
                    stripe_product_id,
                    stripe_price_id,
                    billing_interval,
                    quantity,
                    unit_amount_cents,
                    currency,
                    current_period_start,
                    current_period_end,
                    is_active
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    stripe_billing_account_id,
                    spa_id,
                    environment,
                    item_kind,
                    stripe_item_id,
                    mapping["stripe_product_id"],
                    mapping["stripe_price_id"],
                    mapping["billing_interval"],
                    quantity,
                    mapping["unit_amount_cents"],
                    mapping["currency"],
                    current_period_start,
                    current_period_end,
                    items_should_be_active,
                ),
            )

        synchronized_item_ids.append(
            stripe_item_id
        )

    if "base_plan" not in seen_item_kinds:
        raise StripeServiceError(
            "Stripe Subscription does not contain a "
            "PSP base-plan item."
        )

    placeholders = ", ".join(
        ["%s"] * len(synchronized_item_ids)
    )

    cursor.execute(
        f"""
        UPDATE stripe_subscription_items
        SET
            is_active = FALSE,
            updated_at = NOW()
        WHERE stripe_billing_account_id = %s
          AND environment = %s
          AND is_active = TRUE
          AND stripe_item_id NOT IN ({placeholders})
        """,
        (
            stripe_billing_account_id,
            environment,
            *synchronized_item_ids,
        ),
    )

    cursor.execute(
        """
        UPDATE stripe_billing_accounts
        SET
            stripe_subscription_status = %s,
            trial_start = %s,
            trial_end = %s,
            cancel_at_period_end = %s,
            cancel_at = %s,
            canceled_at = %s,
            ended_at = %s,
            last_synced_at = NOW(),
            updated_at = NOW()
        WHERE stripe_billing_account_id = %s
          AND spa_id = %s
          AND environment = %s
          AND stripe_subscription_id = %s
          AND stripe_customer_id = %s
        """,
        (
            subscription_status,
            trial_start,
            trial_end,
            cancel_at_period_end,
            cancel_at,
            canceled_at,
            ended_at,
            stripe_billing_account_id,
            spa_id,
            environment,
            subscription_id,
            customer_id,
        ),
    )

    if cursor.rowcount != 1:
        raise StripeServiceError(
            "Stripe billing account lifecycle sync did not "
            "update exactly one record."
        )

    # PSP-facing subscription state remains intentionally separate
    # from Stripe's raw billing status. A successful paid conversion
    # after the trial promotes a PSP Trial business to Active.
    #
    # Do not regress an already-Active business back to Trial, and
    # never overwrite a Complimentary business from Stripe billing.
    if subscription_status == "active":
        cursor.execute(
            """
            UPDATE spas
            SET subscription_status = 'Active'
            WHERE spa_id = %s
              AND subscription_status = 'Trial'
            """,
            (spa_id,),
        )

    elif subscription_status in {
        "canceled",
        "incomplete_expired",
    }:
        # A completed Stripe cancellation ends paid PSP access only
        # while this business is using standard billing. Complimentary
        # access is intentionally independent of an old Stripe
        # Subscription ending.
        cursor.execute(
            """
            UPDATE spas
            SET
                subscription_status = 'Canceled',
                access_status = 'restricted'
            WHERE spa_id = %s
              AND billing_mode = 'standard'
              AND subscription_status IN (
                  'Trial',
                  'Active'
              )
            """,
            (spa_id,),
        )

    cursor.execute(
        """
        SELECT subscription_status
        FROM spas
        WHERE spa_id = %s
        LIMIT 1
        """,
        (spa_id,),
    )

    spa_status_row = cursor.fetchone()

    if not spa_status_row:
        raise StripeServiceError(
            "Stripe billing account business could not be resolved."
        )

    psp_subscription_status = str(
        spa_status_row[0] or ""
    ).strip()

    return {
        "stripe_billing_account_id": (
            stripe_billing_account_id
        ),
        "spa_id": spa_id,
        "stripe_customer_id": customer_id,
        "stripe_subscription_id": subscription_id,
        "stripe_subscription_status": (
            subscription_status
        ),
        "psp_subscription_status": (
            psp_subscription_status
        ),
        "trial_start": trial_start,
        "trial_end": trial_end,
        "cancel_at_period_end": (
            cancel_at_period_end
        ),
        "cancel_at": cancel_at,
        "canceled_at": canceled_at,
        "ended_at": ended_at,
        "synchronized_item_ids": (
            synchronized_item_ids
        ),
    }



def get_business_subscription_summary(
    cursor,
    *,
    spa_id,
    environment=None,
    as_of=None,
):
    """
    Return one read-only PSP/Stripe subscription summary for UI use.

    PSP-facing status remains separate from Stripe's raw lifecycle
    status. Billing amount/interval come from the synchronized
    base-plan subscription item rather than from legacy spa fields.
    """
    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    if as_of is None:
        as_of = datetime.now(timezone.utc)

    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    cursor.execute(
        """
        SELECT
            s.subscription_status,
            st.tier_code,
            st.tier_name,
            a.stripe_billing_account_id,
            a.stripe_subscription_status,
            a.trial_start,
            a.trial_end,
            a.cancel_at_period_end,
            a.cancel_at,
            a.canceled_at,
            a.ended_at,
            i.billing_interval,
            i.unit_amount_cents,
            i.currency,
            i.current_period_start,
            i.current_period_end
        FROM spas s
        LEFT JOIN subscription_tiers st
          ON st.subscription_tier_id =
             s.subscription_tier_id
        LEFT JOIN stripe_billing_accounts a
          ON a.spa_id = s.spa_id
         AND a.environment = %s
        LEFT JOIN LATERAL (
            SELECT
                billing_interval,
                unit_amount_cents,
                currency,
                current_period_start,
                current_period_end
            FROM stripe_subscription_items
            WHERE stripe_billing_account_id =
                  a.stripe_billing_account_id
              AND item_kind = 'base_plan'
            ORDER BY
                is_active DESC,
                stripe_subscription_item_id DESC
            LIMIT 1
        ) i ON TRUE
        WHERE s.spa_id = %s
        LIMIT 1
        """,
        (
            environment,
            spa_id,
        ),
    )

    row = cursor.fetchone()

    if not row:
        raise StripeServiceError(
            "PSP business subscription summary could not be resolved."
        )

    (
        psp_status,
        tier_code,
        tier_name,
        stripe_billing_account_id,
        stripe_status,
        trial_start,
        trial_end,
        cancel_at_period_end,
        cancel_at,
        canceled_at,
        ended_at,
        billing_interval,
        unit_amount_cents,
        currency,
        current_period_start,
        current_period_end,
    ) = row

    days_remaining = None

    if (
        str(stripe_status or "").strip().lower() == "trialing"
        and trial_end is not None
    ):
        remaining_seconds = (
            trial_end - as_of
        ).total_seconds()

        if remaining_seconds <= 0:
            days_remaining = 0
        else:
            days_remaining = int(
                (remaining_seconds + 86399) // 86400
            )

    amount_display = None

    if unit_amount_cents is not None:
        amount_display = (
            f"${int(unit_amount_cents) / 100:,.2f}"
        )

    return {
        "psp_status": str(psp_status or "").strip(),
        "tier_code": str(tier_code or "").strip(),
        "tier_name": str(tier_name or "").strip(),
        "stripe_billing_account_id": stripe_billing_account_id,
        "stripe_status": str(stripe_status or "").strip().lower(),
        "trial_start": trial_start,
        "trial_end": trial_end,
        "days_remaining": days_remaining,
        "cancel_at_period_end": bool(cancel_at_period_end),
        "cancel_at": cancel_at,
        "canceled_at": canceled_at,
        "ended_at": ended_at,
        "billing_interval": (
            str(billing_interval or "").strip().lower()
        ),
        "unit_amount_cents": unit_amount_cents,
        "amount_display": amount_display,
        "currency": str(currency or "").strip().lower(),
        "current_period_start": current_period_start,
        "current_period_end": current_period_end,
        "show_trial_card": (
            str(psp_status or "").strip() == "Trial"
            and str(stripe_status or "").strip().lower()
                == "trialing"
        ),
    }


def resume_business_subscription_renewal(
    cursor,
    *,
    spa_id,
    environment=None,
):
    """
    Remove a scheduled end-of-period cancellation from the current
    business Stripe Subscription.

    Stripe remains the billing authority. The returned Subscription
    snapshot is synchronized into PSP immediately; the later Stripe
    lifecycle webhook remains an idempotent confirmation path.
    """
    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    cursor.execute(
        """
        SELECT
            stripe_billing_account_id,
            stripe_subscription_id
        FROM stripe_billing_accounts
        WHERE spa_id = %s
          AND environment = %s
        LIMIT 1
        FOR UPDATE
        """,
        (
            spa_id,
            environment,
        ),
    )

    billing_row = cursor.fetchone()

    if not billing_row:
        raise StripeServiceError(
            "PSP business does not have a Stripe billing account."
        )

    (
        stripe_billing_account_id,
        stripe_subscription_id,
    ) = billing_row

    stripe_subscription_id = str(
        stripe_subscription_id or ""
    ).strip()

    if not stripe_subscription_id:
        raise StripeServiceError(
            "PSP Stripe billing account does not have a "
            "Subscription ID."
        )

    configure_stripe(
        environment=environment
    )

    try:
        subscription = stripe.Subscription.modify(
            stripe_subscription_id,
            cancel_at_period_end=False,
        )
    except Exception as exc:
        raise StripeServiceError(
            "Stripe Subscription renewal could not be restored."
        ) from exc

    synchronized = sync_stripe_subscription_snapshot(
        cursor,
        subscription,
        environment=environment,
    )

    synchronized["stripe_billing_account_id"] = (
        stripe_billing_account_id
    )

    return synchronized


def schedule_business_subscription_cancellation(
    cursor,
    *,
    spa_id,
    environment=None,
):
    """
    Schedule the current business Stripe Subscription to cancel at
    the end of its current trial or billing period.

    Stripe remains the billing authority. The returned Subscription
    snapshot is synchronized into PSP immediately; the later Stripe
    lifecycle webhook remains an idempotent confirmation path.
    """
    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    cursor.execute(
        """
        SELECT
            stripe_billing_account_id,
            stripe_subscription_id
        FROM stripe_billing_accounts
        WHERE spa_id = %s
          AND environment = %s
        LIMIT 1
        FOR UPDATE
        """,
        (
            spa_id,
            environment,
        ),
    )

    billing_row = cursor.fetchone()

    if not billing_row:
        raise StripeServiceError(
            "PSP business does not have a Stripe billing account."
        )

    (
        stripe_billing_account_id,
        stripe_subscription_id,
    ) = billing_row

    stripe_subscription_id = str(
        stripe_subscription_id or ""
    ).strip()

    if not stripe_subscription_id:
        raise StripeServiceError(
            "PSP Stripe billing account does not have a "
            "Subscription ID."
        )

    configure_stripe(
        environment=environment
    )

    try:
        subscription = stripe.Subscription.modify(
            stripe_subscription_id,
            cancel_at_period_end=True,
        )
    except Exception as exc:
        raise StripeServiceError(
            "Stripe Subscription cancellation could not be scheduled."
        ) from exc

    synchronized = sync_stripe_subscription_snapshot(
        cursor,
        subscription,
        environment=environment,
    )

    synchronized["stripe_billing_account_id"] = (
        stripe_billing_account_id
    )

    return synchronized


STRIPE_SUBSCRIPTION_LIFECYCLE_EVENT_TYPES = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}


def sync_stripe_subscription_from_event(
    cursor,
    event,
    *,
    environment=None,
):
    """
    Validate one authenticated Stripe subscription lifecycle event
    and synchronize its Subscription snapshot into PSP.

    If Stripe delivers the event before Checkout provisioning has
    created the PSP billing account, snapshot synchronization fails
    closed. The durable webhook processor can then retain an error
    state and retry the exact event after the dependency exists.
    """
    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    if hasattr(event, "to_dict_recursive"):
        payload = event.to_dict_recursive()
    elif hasattr(event, "to_dict"):
        payload = event.to_dict()
    else:
        payload = dict(event)

    event_id = str(
        payload.get("id")
        or ""
    ).strip()

    event_type = str(
        payload.get("type")
        or ""
    ).strip()

    if not event_id:
        raise StripeServiceError(
            "Stripe subscription lifecycle event ID is missing."
        )

    if (
        event_type
        not in STRIPE_SUBSCRIPTION_LIFECYCLE_EVENT_TYPES
    ):
        raise StripeServiceError(
            "Stripe event is not a supported subscription "
            "lifecycle event."
        )

    expected_livemode = (
        environment == "live"
    )

    if "livemode" not in payload:
        raise StripeServiceError(
            "Stripe subscription lifecycle event environment "
            "is missing."
        )

    if bool(
        payload.get("livemode")
    ) != expected_livemode:
        raise StripeServiceError(
            "Stripe subscription lifecycle event environment "
            "does not match PSP."
        )

    data = payload.get("data") or {}

    if not isinstance(data, dict):
        raise StripeServiceError(
            "Stripe subscription lifecycle event data is invalid."
        )

    subscription = data.get("object") or {}

    if hasattr(subscription, "to_dict_recursive"):
        subscription = subscription.to_dict_recursive()
    elif hasattr(subscription, "to_dict"):
        subscription = subscription.to_dict()
    else:
        subscription = dict(subscription)

    if str(
        subscription.get("object")
        or ""
    ).strip() != "subscription":
        raise StripeServiceError(
            "Stripe subscription lifecycle event object is not "
            "a Subscription."
        )

    subscription_id = str(
        subscription.get("id")
        or ""
    ).strip()

    if not subscription_id:
        raise StripeServiceError(
            "Stripe subscription lifecycle event "
            "Subscription ID is missing."
        )

    # Webhook delivery order is not guaranteed. Retrieve Stripe's
    # current Subscription snapshot before changing PSP billing state
    # so a delayed older event cannot regress a newer state (for
    # example Active back to Trial).
    configure_stripe(
        environment=environment
    )

    try:
        current_subscription = (
            stripe.Subscription.retrieve(
                subscription_id
            )
        )
    except Exception as exc:
        raise StripeServiceError(
            "Current Stripe Subscription could not be retrieved."
        ) from exc

    synchronized = sync_stripe_subscription_snapshot(
        cursor,
        current_subscription,
        environment=environment,
    )

    synchronized["stripe_event_id"] = event_id
    synchronized["event_type"] = event_type

    return synchronized


def create_stripe_checkout_signup(
    cursor,
    *,
    business_name,
    owner_first_name,
    owner_last_name,
    owner_email,
    owner_phone,
    timezone_name,
    billing_interval,
    submitted_discount_code="",
    sms_addon_selected=False,
    ten_dlc_assistance_selected=False,
    terms_version,
    terms_accepted,
    tier_code="solo",
    environment=None,
):
    """
    Create one pending PSP public subscription signup.

    Public self-service purchasing is intentionally limited to
    Solo until additional plans are released.

    This function persists only the validated discount
    classification. The customer-entered private discount code is
    never stored.
    """
    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    tier_code = str(
        tier_code or ""
    ).strip().lower()

    if tier_code != "solo":
        raise ValueError(
            "Solo is the only plan currently available "
            "for public signup."
        )

    billing_interval = normalize_stripe_billing_interval(
        billing_interval
    )

    business_name = str(
        business_name or ""
    ).strip()

    owner_first_name = str(
        owner_first_name or ""
    ).strip()

    owner_last_name = str(
        owner_last_name or ""
    ).strip()

    owner_email = str(
        owner_email or ""
    ).strip().lower()

    timezone_name = str(
        timezone_name or ""
    ).strip()

    terms_version = str(
        terms_version or ""
    ).strip()

    if not business_name:
        raise ValueError(
            "Business name is required."
        )

    if len(business_name) > 150:
        raise ValueError(
            "Business name must contain no more than "
            "150 characters."
        )

    if not owner_first_name:
        raise ValueError(
            "Owner first name is required."
        )

    if len(owner_first_name) > 100:
        raise ValueError(
            "Owner first name must contain no more than "
            "100 characters."
        )

    if not owner_last_name:
        raise ValueError(
            "Owner last name is required."
        )

    if len(owner_last_name) > 100:
        raise ValueError(
            "Owner last name must contain no more than "
            "100 characters."
        )

    if not owner_email:
        raise ValueError(
            "Owner email is required."
        )

    if (
        len(owner_email) > 255
        or "@" not in owner_email
        or any(
            character.isspace()
            for character in owner_email
        )
    ):
        raise ValueError(
            "Please enter a valid owner email address."
        )

    try:
        owner_phone = normalize_user_mobile_phone(
            owner_phone
        )
    except ContactSecurityError as exc:
        raise ValueError(
            str(exc)
        ) from exc

    if not owner_phone:
        raise ValueError(
            "Owner mobile number is required."
        )

    if not timezone_name:
        raise ValueError(
            "Business timezone is required."
        )

    if len(timezone_name) > 100:
        raise ValueError(
            "Business timezone is invalid."
        )

    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError(
            "Business timezone is invalid."
        ) from exc

    if not terms_version:
        raise ValueError(
            "Terms version is required."
        )

    if len(terms_version) > 100:
        raise ValueError(
            "Terms version is invalid."
        )

    if terms_accepted is not True:
        raise ValueError(
            "You must accept the Peach Suite Pro terms "
            "before continuing."
        )

    sms_addon_selected = bool(
        sms_addon_selected
    )

    ten_dlc_assistance_selected = bool(
        ten_dlc_assistance_selected
    )

    if (
        ten_dlc_assistance_selected
        and not sms_addon_selected
    ):
        raise ValueError(
            "10DLC registration assistance requires "
            "SMS to be selected."
        )

    discount_key = (
        validate_subscription_discount_code(
            submitted_discount_code
        )
    )

    # Fail closed if the selected Solo price is not configured
    # for this Stripe environment.
    get_stripe_price_mapping(
        cursor,
        item_kind="base_plan",
        tier_code="solo",
        billing_interval=billing_interval,
        environment=environment,
    )

    if discount_key:
        get_stripe_discount_mapping(
            cursor,
            discount_key=discount_key,
            tier_code="solo",
            billing_interval=billing_interval,
            environment=environment,
        )

    # SMS is an expressed signup interest only at this stage.
    # It is not placed on the subscription until 10DLC approval,
    # but its catalog must still be configured correctly.
    if sms_addon_selected:
        get_stripe_price_mapping(
            cursor,
            item_kind="sms_addon",
            billing_interval=billing_interval,
            environment=environment,
        )

    # 10DLC Setup Assistance is billed separately through
    # the Just Peachy Data Square account, so Stripe catalog
    # configuration is intentionally not required here.

    # Friendly duplicate guard before attempting the INSERT.
    # The database partial unique index remains the authoritative
    # race-condition protection for simultaneous requests.
    cursor.execute(
        """
        SELECT
            stripe_checkout_signup_id,
            signup_status
        FROM stripe_checkout_signups
        WHERE environment = %s
          AND LOWER(owner_email) = LOWER(%s)
          AND tier_code = 'solo'
          AND signup_status IN (
              'pending',
              'checkout_created',
              'checkout_completed',
              'provisioned'
          )
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (
            environment,
            owner_email,
        ),
    )

    existing_active_signup = cursor.fetchone()

    if existing_active_signup:
        raise ValueError(
            "An active Peach Suite Pro Solo signup already exists "
            "for this email address. Please continue the existing "
            "signup or contact support."
        )

    checkout_signup_token = (
        secrets.token_urlsafe(32)
    )

    if len(checkout_signup_token) > 64:
        raise StripeServiceError(
            "Generated checkout signup token is invalid."
        )

    cursor.execute(
        """
        INSERT INTO stripe_checkout_signups (
            checkout_signup_token,
            environment,
            signup_status,
            tier_code,
            billing_interval,
            provider_quantity,
            sms_addon_selected,
            ten_dlc_assistance_selected,
            discount_key,
            business_name,
            owner_first_name,
            owner_last_name,
            owner_email,
            owner_phone,
            timezone_name,
            terms_version,
            terms_accepted_at
        )
        VALUES (
            %s,
            %s,
            'pending',
            'solo',
            %s,
            1,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            NOW()
        )
        ON CONFLICT (
            environment,
            LOWER(owner_email),
            tier_code
        )
        WHERE signup_status IN (
            'pending',
            'checkout_created',
            'checkout_completed',
            'provisioned'
        )
        DO NOTHING
        RETURNING
            stripe_checkout_signup_id,
            checkout_signup_token,
            created_at
        """,
        (
            checkout_signup_token,
            environment,
            billing_interval,
            sms_addon_selected,
            ten_dlc_assistance_selected,
            discount_key,
            business_name,
            owner_first_name,
            owner_last_name,
            owner_email,
            owner_phone,
            timezone_name,
            terms_version,
        ),
    )

    row = cursor.fetchone()

    if not row:
        raise ValueError(
            "An active Peach Suite Pro Solo signup already exists "
            "for this email address. Please continue the existing "
            "signup or contact support."
        )

    return {
        "stripe_checkout_signup_id": row[0],
        "checkout_signup_token": row[1],
        "created_at": row[2],
        "environment": environment,
        "tier_code": "solo",
        "billing_interval": billing_interval,
        "provider_quantity": 1,
        "sms_addon_selected": sms_addon_selected,
        "ten_dlc_assistance_selected": (
            ten_dlc_assistance_selected
        ),
        "discount_key": discount_key,
        "owner_phone": owner_phone,
    }


def get_stripe_checkout_signup(
    cursor,
    *,
    stripe_checkout_signup_id,
    environment=None,
):
    """
    Return one PSP Stripe checkout signup from the authoritative
    server-side record.

    Public routes should use this instead of trusting signup data
    from browser form fields or the signed session.
    """
    try:
        signup_id = int(
            stripe_checkout_signup_id
        )
    except (TypeError, ValueError):
        raise StripeServiceError(
            "Stripe checkout signup is invalid."
        )

    if signup_id <= 0:
        raise StripeServiceError(
            "Stripe checkout signup is invalid."
        )

    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    cursor.execute(
        """
        SELECT
            stripe_checkout_signup_id,
            checkout_signup_token,
            environment,
            signup_status,
            tier_code,
            billing_interval,
            provider_quantity,
            sms_addon_selected,
            ten_dlc_assistance_selected,
            discount_key,
            business_name,
            owner_first_name,
            owner_last_name,
            owner_email,
            owner_phone,
            timezone_name,
            terms_version,
            terms_accepted_at,
            phone_verified_at,
            phone_verification_failed_count,
            phone_verification_window_started_at,
            phone_verification_last_failed_at,
            phone_verification_locked_until,
            stripe_checkout_session_id,
            stripe_customer_id,
            stripe_subscription_id,
            checkout_expires_at,
            checkout_completed_at,
            provisioned_at,
            canceled_at,
            created_at,
            updated_at
        FROM stripe_checkout_signups
        WHERE stripe_checkout_signup_id = %s
          AND environment = %s
        LIMIT 1
        """,
        (
            signup_id,
            environment,
        ),
    )

    row = cursor.fetchone()

    if not row:
        return None

    return {
        "stripe_checkout_signup_id": row[0],
        "checkout_signup_token": row[1],
        "environment": row[2],
        "signup_status": row[3],
        "tier_code": row[4],
        "billing_interval": row[5],
        "provider_quantity": row[6],
        "sms_addon_selected": bool(row[7]),
        "ten_dlc_assistance_selected": bool(row[8]),
        "discount_key": row[9],
        "business_name": row[10],
        "owner_first_name": row[11],
        "owner_last_name": row[12],
        "owner_email": row[13],
        "owner_phone": row[14],
        "timezone_name": row[15],
        "terms_version": row[16],
        "terms_accepted_at": row[17],
        "phone_verified_at": row[18],
        "phone_verification_failed_count": row[19],
        "phone_verification_window_started_at": row[20],
        "phone_verification_last_failed_at": row[21],
        "phone_verification_locked_until": row[22],
        "stripe_checkout_session_id": row[23],
        "stripe_customer_id": row[24],
        "stripe_subscription_id": row[25],
        "checkout_expires_at": row[26],
        "checkout_completed_at": row[27],
        "provisioned_at": row[28],
        "canceled_at": row[29],
        "created_at": row[30],
        "updated_at": row[31],
    }


STRIPE_SOLO_TRIAL_DAYS = 10


def create_stripe_checkout_session(
    cursor,
    *,
    stripe_checkout_signup_id,
    success_url,
    cancel_url,
    environment=None,
):
    """
    Create or recover the Stripe-hosted Checkout Session for one
    phone-verified PSP Solo signup.

    The caller owns the database transaction.

    PSP signup PII remains in PSP. Stripe metadata receives only
    the opaque checkout signup token. Normal Stripe billing fields,
    such as customer_email, are supplied where required.
    """
    try:
        signup_id = int(
            stripe_checkout_signup_id
        )
    except (TypeError, ValueError):
        raise StripeServiceError(
            "Stripe checkout signup is invalid."
        )

    if signup_id <= 0:
        raise StripeServiceError(
            "Stripe checkout signup is invalid."
        )

    environment = normalize_stripe_environment(
        environment
        or get_stripe_environment()
    )

    success_url = str(
        success_url or ""
    ).strip()

    cancel_url = str(
        cancel_url or ""
    ).strip()

    if not success_url:
        raise StripeServiceError(
            "Stripe Checkout success URL is required."
        )

    if not cancel_url:
        raise StripeServiceError(
            "Stripe Checkout cancel URL is required."
        )

    cursor.execute(
        """
        SELECT
            checkout_signup_token,
            environment,
            signup_status,
            tier_code,
            billing_interval,
            provider_quantity,
            sms_addon_selected,
            ten_dlc_assistance_selected,
            discount_key,
            owner_email,
            terms_version,
            terms_accepted_at,
            phone_verified_at,
            stripe_checkout_session_id
        FROM stripe_checkout_signups
        WHERE stripe_checkout_signup_id = %s
          AND environment = %s
        FOR UPDATE
        """,
        (
            signup_id,
            environment,
        ),
    )

    row = cursor.fetchone()

    if not row:
        raise StripeServiceError(
            "Stripe checkout signup is no longer available."
        )

    (
        checkout_signup_token,
        signup_environment,
        signup_status,
        tier_code,
        billing_interval,
        provider_quantity,
        sms_addon_selected,
        ten_dlc_assistance_selected,
        discount_key,
        owner_email,
        terms_version,
        terms_accepted_at,
        phone_verified_at,
        existing_checkout_session_id,
    ) = row

    checkout_signup_token = str(
        checkout_signup_token or ""
    ).strip()

    tier_code = str(
        tier_code or ""
    ).strip().lower()

    owner_email = str(
        owner_email or ""
    ).strip().lower()

    terms_version = str(
        terms_version or ""
    ).strip()

    if signup_environment != environment:
        raise StripeServiceError(
            "Stripe signup environment does not match."
        )

    if tier_code != "solo":
        raise StripeServiceError(
            "Only Solo may use this Checkout flow."
        )

    if int(provider_quantity or 0) != 1:
        raise StripeServiceError(
            "Solo Checkout requires exactly one provider."
        )

    billing_interval = (
        normalize_stripe_billing_interval(
            billing_interval
        )
    )

    if not checkout_signup_token:
        raise StripeServiceError(
            "Stripe checkout signup token is missing."
        )

    if not owner_email:
        raise StripeServiceError(
            "Stripe checkout owner email is missing."
        )

    if (
        not terms_version
        or terms_accepted_at is None
    ):
        raise StripeServiceError(
            "Subscription Terms must be accepted "
            "before Stripe Checkout."
        )

    if phone_verified_at is None:
        raise StripeServiceError(
            "Mobile verification must be completed "
            "before Stripe Checkout."
        )

    configure_stripe(
        environment=environment
    )

    replacement_of_checkout_session_id = None

    # If PSP already recorded a Checkout Session, recover an open
    # session. An expired session may be replaced safely for the
    # same logical signup. A completed session must never create
    # another subscription attempt.
    if existing_checkout_session_id:
        try:
            existing_session = (
                stripe.checkout.Session.retrieve(
                    existing_checkout_session_id
                )
            )
        except Exception as exc:
            raise StripeServiceError(
                "Existing Stripe Checkout Session "
                "could not be retrieved."
            ) from exc

        existing_data = (
            existing_session.to_dict()
        )

        expected_livemode = (
            environment == "live"
        )

        if bool(
            existing_data.get("livemode")
        ) != expected_livemode:
            raise StripeServiceError(
                "Existing Stripe Checkout Session "
                "environment does not match PSP."
            )

        existing_metadata = dict(
            existing_data.get("metadata")
            or {}
        )

        if (
            existing_metadata.get(
                "psp_checkout_signup_token"
            )
            != checkout_signup_token
        ):
            raise StripeServiceError(
                "Existing Stripe Checkout Session "
                "does not match this PSP signup."
            )

        existing_status = str(
            existing_data.get("status")
            or ""
        ).strip().lower()

        if existing_status == "open":
            return {
                "stripe_checkout_session_id": (
                    existing_data.get("id")
                ),
                "checkout_url": (
                    existing_data.get("url")
                ),
                "expires_at": (
                    existing_data.get("expires_at")
                ),
                "status": existing_status,
                "existing": True,
            }

        if existing_status == "complete":
            raise StripeServiceError(
                "Stripe Checkout has already been completed "
                "for this signup."
            )

        if existing_status != "expired":
            raise StripeServiceError(
                "Existing Stripe Checkout Session "
                "has an unsupported status."
            )

        replacement_of_checkout_session_id = str(
            existing_data.get("id")
            or existing_checkout_session_id
        ).strip()

        if signup_status != "checkout_created":
            raise StripeServiceError(
                "Expired Stripe Checkout Session "
                "does not match PSP signup state."
            )

    elif signup_status != "pending":
        raise StripeServiceError(
            "This signup is not ready to create "
            "a new Stripe Checkout Session."
        )

    base_price = get_stripe_price_mapping(
        cursor,
        item_kind="base_plan",
        tier_code="solo",
        billing_interval=billing_interval,
        environment=environment,
    )

    line_items = [
        {
            "price": (
                base_price["stripe_price_id"]
            ),
            "quantity": 1,
        }
    ]

    # SMS is only an expressed interest during signup.
    # It is NOT added to the subscription until 10DLC approval.
    sms_addon_selected = bool(
        sms_addon_selected
    )

    ten_dlc_assistance_selected = bool(
        ten_dlc_assistance_selected
    )

    if (
        ten_dlc_assistance_selected
        and not sms_addon_selected
    ):
        raise StripeServiceError(
            "10DLC assistance requires SMS interest."
        )

    # 10DLC Setup Assistance is billed separately through
    # the Just Peachy Data Square account. The customer's
    # selection remains stored in PSP, but the $50 service
    # charge must never be added to Stripe subscription
    # Checkout.
    discounts = []

    if discount_key:
        discount_mapping = (
            get_stripe_discount_mapping(
                cursor,
                discount_key=discount_key,
                tier_code="solo",
                billing_interval=billing_interval,
                environment=environment,
            )
        )

        discounts.append(
            {
                "coupon": (
                    discount_mapping[
                        "stripe_coupon_id"
                    ]
                )
            }
        )

    metadata = {
        "psp_checkout_signup_token": (
            checkout_signup_token
        )
    }

    checkout_params = {
        "mode": "subscription",
        "line_items": line_items,
        "customer_email": owner_email,
        "client_reference_id": (
            checkout_signup_token
        ),
        "success_url": success_url,
        "cancel_url": cancel_url,
        "payment_method_collection": "always",
        "metadata": metadata,
        "subscription_data": {
            "trial_period_days": (
                STRIPE_SOLO_TRIAL_DAYS
            ),
            "trial_settings": {
                "end_behavior": {
                    "missing_payment_method": "cancel",
                },
            },
            "metadata": metadata,
        },
        "idempotency_key": (
            (
                "psp-checkout-replacement-v1-"
                f"{environment}-{signup_id}-"
                f"{replacement_of_checkout_session_id}"
            )
            if replacement_of_checkout_session_id
            else (
                "psp-checkout-signup-v1-"
                f"{environment}-{signup_id}"
            )
        ),
    }

    if discounts:
        checkout_params[
            "discounts"
        ] = discounts

    try:
        checkout_session = (
            stripe.checkout.Session.create(
                **checkout_params
            )
        )

    except stripe.InvalidRequestError:
        # Stripe caches validation failures under an idempotency key.
        # A definite InvalidRequestError means no Checkout Session was
        # created, so it is safe to retry once with a fresh key. This
        # allows a corrected external Stripe configuration issue to be
        # retried while preserving the stable key for ambiguous/network
        # failures where duplicate protection is still required.
        retry_token = secrets.token_hex(12)

        retry_params = dict(checkout_params)

        retry_params["idempotency_key"] = (
            (
                "psp-checkout-replacement-retry-v1-"
                f"{environment}-{signup_id}-"
                f"{replacement_of_checkout_session_id}-"
                f"{retry_token}"
            )
            if replacement_of_checkout_session_id
            else (
                "psp-checkout-signup-retry-v1-"
                f"{environment}-{signup_id}-"
                f"{retry_token}"
            )
        )

        try:
            checkout_session = (
                stripe.checkout.Session.create(
                    **retry_params
                )
            )
        except Exception as exc:
            raise StripeServiceError(
                "Stripe Checkout Session could not be created."
            ) from exc

    except Exception as exc:
        raise StripeServiceError(
            "Stripe Checkout Session could not be created."
        ) from exc

    checkout_data = (
        checkout_session.to_dict()
    )

    checkout_session_id = str(
        checkout_data.get("id")
        or ""
    ).strip()

    checkout_url = str(
        checkout_data.get("url")
        or ""
    ).strip()

    checkout_expires_at = (
        checkout_data.get("expires_at")
    )

    if not checkout_session_id:
        raise StripeServiceError(
            "Stripe did not return a Checkout Session ID."
        )

    if not checkout_url:
        raise StripeServiceError(
            "Stripe did not return a Checkout URL."
        )

    expected_livemode = (
        environment == "live"
    )

    if bool(
        checkout_data.get("livemode")
    ) != expected_livemode:
        raise StripeServiceError(
            "Stripe Checkout Session environment "
            "does not match PSP."
        )

    returned_metadata = dict(
        checkout_data.get("metadata")
        or {}
    )

    if (
        returned_metadata.get(
            "psp_checkout_signup_token"
        )
        != checkout_signup_token
    ):
        raise StripeServiceError(
            "Stripe Checkout Session metadata "
            "does not match PSP signup."
        )

    cursor.execute(
        """
        UPDATE stripe_checkout_signups
        SET
            signup_status = 'checkout_created',
            stripe_checkout_session_id = %s,
            checkout_expires_at =
                CASE
                    WHEN %s IS NULL
                    THEN NULL
                    ELSE to_timestamp(%s)
                END,
            updated_at = NOW()
        WHERE stripe_checkout_signup_id = %s
          AND environment = %s
          AND phone_verified_at IS NOT NULL
          AND (
              (
                  %s IS NULL
                  AND signup_status = 'pending'
                  AND stripe_checkout_session_id IS NULL
              )
              OR
              (
                  %s IS NOT NULL
                  AND signup_status = 'checkout_created'
                  AND stripe_checkout_session_id = %s
              )
          )
        RETURNING stripe_checkout_signup_id
        """,
        (
            checkout_session_id,
            checkout_expires_at,
            checkout_expires_at,
            signup_id,
            environment,
            replacement_of_checkout_session_id,
            replacement_of_checkout_session_id,
            replacement_of_checkout_session_id,
        ),
    )

    if not cursor.fetchone():
        raise StripeServiceError(
            "Stripe Checkout Session could not be "
            "attached to the PSP signup."
        )

    return {
        "stripe_checkout_session_id": (
            checkout_session_id
        ),
        "checkout_url": checkout_url,
        "expires_at": checkout_expires_at,
        "status": checkout_data.get("status"),
        "existing": False,
    }
