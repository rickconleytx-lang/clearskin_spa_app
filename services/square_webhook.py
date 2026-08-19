import base64
import hashlib
import hmac
import json


class SquareWebhookConfigurationError(Exception):
    """Raised when Square webhook verification is not configured."""


class SquareWebhookVerificationError(Exception):
    """Raised when a Square webhook cannot be authenticated."""


def verify_square_webhook_signature(
    raw_body,
    signature_value,
    signature_key,
    notification_url,
):
    """
    Verify a Square webhook HMAC-SHA256 signature.

    Square signs:

        notification URL + unaltered raw request body

    The resulting digest is Base64 encoded and compared with
    the x-square-hmacsha256-signature request header.
    """

    if not isinstance(raw_body, (bytes, bytearray)):
        raise SquareWebhookVerificationError(
            "Webhook body must be raw bytes."
        )

    normalized_signature = str(
        signature_value or ""
    ).strip()

    if not normalized_signature:
        raise SquareWebhookVerificationError(
            "Missing Square webhook signature."
        )

    normalized_signature_key = str(
        signature_key or ""
    ).strip()

    if not normalized_signature_key:
        raise SquareWebhookConfigurationError(
            "Square webhook signature key is not configured."
        )

    normalized_notification_url = str(
        notification_url or ""
    ).strip()

    if not normalized_notification_url:
        raise SquareWebhookConfigurationError(
            "Square webhook notification URL is not configured."
        )

    signed_payload = (
        normalized_notification_url.encode("utf-8")
        + bytes(raw_body)
    )

    expected_signature = base64.b64encode(
        hmac.new(
            normalized_signature_key.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).digest()
    ).decode("ascii")

    if not hmac.compare_digest(
        expected_signature,
        normalized_signature,
    ):
        raise SquareWebhookVerificationError(
            "Invalid Square webhook signature."
        )

    return True

def _get_webhook_db_connection():
    """
    Import lazily to avoid an app/service circular import while
    app.py is loading.
    """
    from app import get_db_connection
    return get_db_connection()


def extract_square_event_metadata(event):
    """
    Extract the identifiers PSP needs to safely record and route
    one verified Square webhook event.

    No workspace is inferred here.
    """
    if not isinstance(event, dict):
        raise ValueError("Square webhook payload must be an object.")

    event_id = str(
        event.get("event_id") or ""
    ).strip()

    event_type = str(
        event.get("type") or ""
    ).strip()

    if not event_id:
        raise ValueError(
            "Square webhook payload is missing event_id."
        )

    if not event_type:
        raise ValueError(
            "Square webhook payload is missing type."
        )

    merchant_id = str(
        event.get("merchant_id") or ""
    ).strip() or None

    location_id = str(
        event.get("location_id") or ""
    ).strip() or None

    data = event.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    data_object = data.get("object") or {}
    if not isinstance(data_object, dict):
        data_object = {}

    payment = data_object.get("payment") or {}
    if not isinstance(payment, dict):
        payment = {}

    payment_id = str(
        payment.get("id")
        or (
            data.get("id")
            if data.get("type") == "payment"
            else ""
        )
        or ""
    ).strip() or None

    order_id = str(
        payment.get("order_id") or ""
    ).strip() or None

    payment_location_id = str(
        payment.get("location_id") or ""
    ).strip() or None

    payment_merchant_id = str(
        payment.get("merchant_id") or ""
    ).strip() or None

    return {
        "event_id": event_id,
        "event_type": event_type,
        "merchant_id": (
            merchant_id
            or payment_merchant_id
        ),
        "location_id": (
            location_id
            or payment_location_id
        ),
        "payment_id": payment_id,
        "order_id": order_id,
    }


def _resolve_square_webhook_workspace(
    cursor,
    *,
    environment,
    merchant_id,
    location_id,
):
    """
    Resolve a verified Square event to exactly one PSP workspace.

    Location is authoritative when available. Merchant-only
    routing is accepted only when it resolves to exactly one
    connected PSP workspace in this environment.
    """
    if location_id:
        cursor.execute("""
            SELECT
                sc.square_connection_id,
                sc.spa_id,
                sc.business_unit_id
            FROM square_locations sl
            JOIN square_connections sc
              ON sc.square_connection_id =
                    sl.square_connection_id
             AND sc.spa_id = sl.spa_id
             AND sc.business_unit_id =
                    sl.business_unit_id
             AND sc.environment = sl.environment
            WHERE sl.environment = %s
              AND sl.square_location_id = %s
              AND sl.is_active = TRUE
              AND sc.connection_status = 'connected'
              AND (
                    %s IS NULL
                    OR sc.merchant_id = %s
              )
            LIMIT 2
        """, (
            environment,
            location_id,
            merchant_id,
            merchant_id,
        ))

        rows = cursor.fetchall()

        if len(rows) == 1:
            return {
                "square_connection_id": rows[0][0],
                "spa_id": rows[0][1],
                "business_unit_id": rows[0][2],
            }

        return None

    if not merchant_id:
        return None

    cursor.execute("""
        SELECT
            square_connection_id,
            spa_id,
            business_unit_id
        FROM square_connections
        WHERE environment = %s
          AND merchant_id = %s
          AND connection_status = 'connected'
        ORDER BY square_connection_id
        LIMIT 2
    """, (
        environment,
        merchant_id,
    ))

    rows = cursor.fetchall()

    if len(rows) != 1:
        return None

    return {
        "square_connection_id": rows[0][0],
        "spa_id": rows[0][1],
        "business_unit_id": rows[0][2],
    }


def record_verified_square_event(
    event,
    *,
    environment,
    connection=None,
):
    """
    Idempotently record one signature-verified Square event.

    This function records and routes the webhook only.
    It does not create Income or inventory movements.
    """
    environment = str(
        environment or ""
    ).strip().lower()

    if environment not in {
        "sandbox",
        "production",
    }:
        raise ValueError(
            "Square webhook environment is invalid."
        )

    metadata = extract_square_event_metadata(event)

    owns_connection = connection is None

    if owns_connection:
        connection = _get_webhook_db_connection()

    cursor = connection.cursor()

    try:
        workspace = _resolve_square_webhook_workspace(
            cursor,
            environment=environment,
            merchant_id=metadata["merchant_id"],
            location_id=metadata["location_id"],
        )

        if workspace:
            routing_status = "routed"
            square_connection_id = workspace[
                "square_connection_id"
            ]
            spa_id = workspace["spa_id"]
            business_unit_id = workspace[
                "business_unit_id"
            ]
        else:
            routing_status = "unrouted"
            square_connection_id = None
            spa_id = None
            business_unit_id = None

        cursor.execute("""
            INSERT INTO square_webhook_events (
                environment,
                square_event_id,
                event_type,
                merchant_id,
                square_location_id,
                square_payment_id,
                square_order_id,
                square_connection_id,
                spa_id,
                business_unit_id,
                signature_valid,
                routing_status,
                processing_status,
                payload,
                processing_attempts,
                error_message
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                TRUE, %s, 'received',
                %s::jsonb, 0, NULL
            )
            ON CONFLICT (
                environment,
                square_event_id
            )
            DO NOTHING
            RETURNING
                square_webhook_event_id,
                routing_status,
                processing_status,
                spa_id,
                business_unit_id
        """, (
            environment,
            metadata["event_id"],
            metadata["event_type"],
            metadata["merchant_id"],
            metadata["location_id"],
            metadata["payment_id"],
            metadata["order_id"],
            square_connection_id,
            spa_id,
            business_unit_id,
            routing_status,
            json.dumps(
                event,
                separators=(",", ":"),
            ),
        ))

        row = cursor.fetchone()

        duplicate = row is None

        if duplicate:
            cursor.execute("""
                SELECT
                    square_webhook_event_id,
                    routing_status,
                    processing_status,
                    spa_id,
                    business_unit_id
                FROM square_webhook_events
                WHERE environment = %s
                  AND square_event_id = %s
                LIMIT 1
            """, (
                environment,
                metadata["event_id"],
            ))

            row = cursor.fetchone()

            if not row:
                raise RuntimeError(
                    "Duplicate Square webhook event "
                    "could not be resolved."
                )

        if owns_connection:
            connection.commit()

        return {
            "square_webhook_event_id": row[0],
            "routing_status": row[1],
            "processing_status": row[2],
            "spa_id": row[3],
            "business_unit_id": row[4],
            "duplicate": duplicate,
            "event_id": metadata["event_id"],
            "event_type": metadata["event_type"],
            "payment_id": metadata["payment_id"],
            "order_id": metadata["order_id"],
        }

    except Exception:
        if owns_connection:
            connection.rollback()

        raise

    finally:
        cursor.close()

        if owns_connection:
            connection.close()

def process_square_webhook(environment):
    """
    Authenticate, validate, route, and record one Square webhook.

    Financial and inventory processing are intentionally separate.
    """
    import os

    from flask import jsonify, request

    normalized_environment = str(
        environment or ""
    ).strip().lower()

    if normalized_environment not in {
        "sandbox",
        "production",
    }:
        return jsonify({
            "success": False,
            "error": "Invalid Square webhook environment.",
        }), 404

    env_prefix = (
        "SQUARE_"
        + normalized_environment.upper()
        + "_WEBHOOK_"
    )

    raw_body = request.get_data(
        cache=True,
        as_text=False,
    )

    signature_value = request.headers.get(
        "x-square-hmacsha256-signature"
    )

    try:
        verify_square_webhook_signature(
            raw_body=raw_body,
            signature_value=signature_value,
            signature_key=os.getenv(
                env_prefix + "SIGNATURE_KEY"
            ),
            notification_url=os.getenv(
                env_prefix + "NOTIFICATION_URL"
            ),
        )

    except SquareWebhookConfigurationError:
        print(
            "[SQUARE WEBHOOK UNAVAILABLE]",
            {
                "environment": normalized_environment,
                "reason":
                    "Webhook verification is not configured.",
            },
            flush=True,
        )

        return jsonify({
            "success": False,
            "error": "Webhook verification unavailable.",
        }), 503

    except SquareWebhookVerificationError as error:
        print(
            "[SQUARE WEBHOOK REJECTED]",
            {
                "environment": normalized_environment,
                "reason": str(error),
            },
            flush=True,
        )

        return jsonify({
            "success": False,
            "error": "Webhook authentication failed.",
        }), 401

    square_environment_header = str(
        request.headers.get(
            "square-environment"
        )
        or ""
    ).strip().lower()

    if (
        square_environment_header
        and square_environment_header
            != normalized_environment
    ):
        print(
            "[SQUARE WEBHOOK REJECTED]",
            {
                "environment": normalized_environment,
                "reason":
                    "Square environment header mismatch.",
            },
            flush=True,
        )

        return jsonify({
            "success": False,
            "error": "Webhook environment mismatch.",
        }), 400

    try:
        event = json.loads(
            raw_body.decode("utf-8")
        )

        if not isinstance(event, dict):
            raise ValueError(
                "Square webhook payload must be an object."
            )

        receipt = record_verified_square_event(
            event,
            environment=normalized_environment,
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        print(
            "[SQUARE WEBHOOK REJECTED]",
            {
                "environment": normalized_environment,
                "reason": str(error),
            },
            flush=True,
        )

        return jsonify({
            "success": False,
            "error": "Invalid webhook payload.",
        }), 400

    except Exception as error:
        print(
            "[SQUARE WEBHOOK STORAGE ERROR]",
            {
                "environment": normalized_environment,
                "error_type": type(error).__name__,
            },
            flush=True,
        )

        return jsonify({
            "success": False,
            "error": "Webhook storage failed.",
        }), 500

    try:
        from services.square_webhook_retail import (
            process_recorded_square_retail_event,
        )

        processing_result = (
            process_recorded_square_retail_event(
                receipt["square_webhook_event_id"]
            )
        )

    except Exception as error:
        print(
            "[SQUARE WEBHOOK PROCESSING ERROR]",
            {
                "environment": normalized_environment,
                "event_id": receipt["event_id"],
                "event_type": receipt["event_type"],
                "payment_id": receipt["payment_id"],
                "error_type": type(error).__name__,
            },
            flush=True,
        )

        return jsonify({
            "success": False,
            "error": "Webhook processing failed.",
        }), 500

    print(
        "[SQUARE WEBHOOK VERIFIED]",
        {
            "environment": normalized_environment,
            "event_id": receipt["event_id"],
            "event_type": receipt["event_type"],
            "payment_id": receipt["payment_id"],
            "duplicate": receipt["duplicate"],
            "routed": receipt["spa_id"] is not None,
            "processing_status": (
                processing_result.get("status")
            ),
        },
        flush=True,
    )

    return "", 204

