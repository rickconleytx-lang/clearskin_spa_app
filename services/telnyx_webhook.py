import base64
import binascii
import json
import os
import time
from datetime import datetime

from flask import jsonify, request
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey


TELNYX_TIMESTAMP_TOLERANCE_SECONDS = 300


class TelnyxWebhookConfigurationError(Exception):
    """Raised when webhook verification is not configured."""


class TelnyxWebhookVerificationError(Exception):
    """Raised when a webhook cannot be authenticated."""


def _decode_base64(value, field_name):
    """
    Decode a Base64 value after removing surrounding whitespace.
    """

    normalized_value = "".join(
        str(value or "").split()
    )

    if not normalized_value:
        raise TelnyxWebhookVerificationError(
            f"Missing {field_name}."
        )

    try:
        return base64.b64decode(
            normalized_value,
            validate=True,
        )

    except (binascii.Error, ValueError) as error:
        raise TelnyxWebhookVerificationError(
            f"Invalid {field_name} encoding."
        ) from error


def load_telnyx_verify_key(public_key_value):
    """
    Build an Ed25519 verification key from the Telnyx
    Base64-encoded account public key.
    """

    if not public_key_value:
        raise TelnyxWebhookConfigurationError(
            "TELNYX_PUBLIC_KEY is not configured."
        )

    public_key_bytes = _decode_base64(
        public_key_value,
        "Telnyx public key",
    )

    if len(public_key_bytes) != 32:
        raise TelnyxWebhookConfigurationError(
            "TELNYX_PUBLIC_KEY must decode to 32 bytes."
        )

    try:
        return VerifyKey(public_key_bytes)

    except (TypeError, ValueError) as error:
        raise TelnyxWebhookConfigurationError(
            "TELNYX_PUBLIC_KEY is invalid."
        ) from error


def verify_telnyx_webhook_signature(
    raw_body,
    signature_value,
    timestamp_value,
    public_key_value,
    *,
    current_time=None,
    tolerance_seconds=TELNYX_TIMESTAMP_TOLERANCE_SECONDS,
):
    """
    Verify a Telnyx Ed25519 webhook signature.

    Telnyx signs:
        timestamp + "|" + unaltered raw request body
    """

    if not isinstance(raw_body, (bytes, bytearray)):
        raise TelnyxWebhookVerificationError(
            "Webhook body must be raw bytes."
        )

    normalized_timestamp = str(
        timestamp_value or ""
    ).strip()

    if not normalized_timestamp:
        raise TelnyxWebhookVerificationError(
            "Missing Telnyx timestamp."
        )

    try:
        timestamp_number = int(normalized_timestamp)

    except (TypeError, ValueError) as error:
        raise TelnyxWebhookVerificationError(
            "Invalid Telnyx timestamp."
        ) from error

    now = int(
        time.time()
        if current_time is None
        else current_time
    )

    if abs(now - timestamp_number) > tolerance_seconds:
        raise TelnyxWebhookVerificationError(
            "Telnyx timestamp is outside the allowed window."
        )

    signature_bytes = _decode_base64(
        signature_value,
        "Telnyx signature",
    )

    if len(signature_bytes) != 64:
        raise TelnyxWebhookVerificationError(
            "Telnyx signature must decode to 64 bytes."
        )

    verify_key = load_telnyx_verify_key(
        public_key_value
    )

    signed_payload = (
        normalized_timestamp.encode("ascii")
        + b"|"
        + bytes(raw_body)
    )

    try:
        verify_key.verify(
            signed_payload,
            signature_bytes,
        )

    except BadSignatureError as error:
        raise TelnyxWebhookVerificationError(
            "Telnyx signature verification failed."
        ) from error

    return True


def parse_telnyx_event(raw_body):
    """
    Parse and validate the common Telnyx event envelope.
    """

    try:
        event = json.loads(raw_body)

    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(
            "Webhook body is not valid JSON."
        ) from error

    if not isinstance(event, dict):
        raise ValueError(
            "Webhook body must be a JSON object."
        )

    event_data = event.get("data")

    if not isinstance(event_data, dict):
        raise ValueError(
            "Webhook is missing the data object."
        )

    event_id = event_data.get("id")
    event_type = event_data.get("event_type")
    payload = event_data.get("payload")

    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError(
            "Webhook is missing data.id."
        )

    if (
        not isinstance(event_type, str)
        or not event_type.strip()
    ):
        raise ValueError(
            "Webhook is missing data.event_type."
        )

    if not isinstance(payload, dict):
        raise ValueError(
            "Webhook is missing data.payload."
        )

    return event



def _normalize_phone_number(value):
    """
    Preserve an E.164-style phone number without formatting
    characters. Telnyx normally supplies E.164 values.
    """

    if isinstance(value, dict):
        value = value.get("phone_number")

    value = str(value or "").strip()

    if not value:
        return None

    digits = "".join(
        character
        for character in value
        if character.isdigit()
    )

    if not digits:
        return None

    return f"+{digits}"


def _phone_digits(value):
    normalized = _normalize_phone_number(value)

    if not normalized:
        return None

    return normalized.lstrip("+")


def _first_to_entry(payload):
    recipients = payload.get("to")

    if isinstance(recipients, list) and recipients:
        first_recipient = recipients[0]

        if isinstance(first_recipient, dict):
            return first_recipient

        return {
            "phone_number": first_recipient,
        }

    if isinstance(recipients, dict):
        return recipients

    if isinstance(recipients, str):
        return {
            "phone_number": recipients,
        }

    return {}


def _parse_event_timestamp(value):
    value = str(value or "").strip()

    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

    except ValueError:
        return None


def _safe_integer(value):
    try:
        return int(value)

    except (TypeError, ValueError):
        return None


def _sanitize_error_list(errors):
    safe_errors = []

    if not isinstance(errors, list):
        return safe_errors

    for error in errors:
        if not isinstance(error, dict):
            continue

        safe_errors.append({
            "code": error.get("code"),
            "title": error.get("title"),
            "detail": error.get("detail"),
        })

    return safe_errors


def build_sanitized_telnyx_event(event):
    """
    Retain useful delivery metadata without duplicating message
    text, phone numbers, media URLs, or webhook URLs.
    """

    event_data = event["data"]
    payload = event_data["payload"]
    meta = event.get("meta")

    if not isinstance(meta, dict):
        meta = {}

    recipient_statuses = []

    recipients = payload.get("to")

    if isinstance(recipients, list):
        for recipient in recipients:
            if not isinstance(recipient, dict):
                continue

            recipient_statuses.append({
                "status": recipient.get("status"),
            })

    media = payload.get("media")

    media_count = (
        len(media)
        if isinstance(media, list)
        else 0
    )

    text = payload.get("text")

    return {
        "data": {
            "record_type": event_data.get("record_type"),
            "id": event_data.get("id"),
            "event_type": event_data.get("event_type"),
            "occurred_at": event_data.get("occurred_at"),
            "payload": {
                "record_type": payload.get("record_type"),
                "id": payload.get("id"),
                "direction": payload.get("direction"),
                "type": payload.get("type"),
                "messaging_profile_id": payload.get(
                    "messaging_profile_id"
                ),
                "autoresponse_type": payload.get(
                    "autoresponse_type"
                ),
                "parts": payload.get("parts"),
                "encoding": payload.get("encoding"),
                "recipient_statuses": recipient_statuses,
                "errors": _sanitize_error_list(
                    payload.get("errors")
                ),
                "has_text": (
                    isinstance(text, str)
                    and bool(text)
                ),
                "media_count": media_count,
            },
        },
        "meta": {
            "attempt": meta.get("attempt"),
        },
    }


def extract_telnyx_event_metadata(event):
    event_data = event["data"]
    payload = event_data["payload"]

    event_type = event_data["event_type"].strip()
    direction = str(
        payload.get("direction") or ""
    ).strip().lower()

    from_phone = _normalize_phone_number(
        payload.get("from")
    )

    first_recipient = _first_to_entry(payload)

    to_phone = _normalize_phone_number(
        first_recipient
    )

    if (
        event_type == "message.received"
        or direction == "inbound"
    ):
        routing_phone = to_phone
    else:
        routing_phone = from_phone

    meta = event.get("meta")

    if not isinstance(meta, dict):
        meta = {}

    return {
        "event_id": event_data["id"].strip(),
        "event_type": event_type,
        "event_occurred_at": _parse_event_timestamp(
            event_data.get("occurred_at")
        ),
        "provider_message_id": payload.get("id"),
        "sender_phone": from_phone,
        "receiving_phone": to_phone,
        "routing_phone": routing_phone,
        "messaging_profile_id": payload.get(
            "messaging_profile_id"
        ),
        "brand_id": (
            payload.get("tcr_brand_id")
            or payload.get("brand_id")
        ),
        "campaign_id": (
            payload.get("tcr_campaign_id")
            or payload.get("campaign_id")
        ),
        "delivery_attempt": _safe_integer(
            meta.get("attempt")
        ),
        "sanitized_payload": (
            build_sanitized_telnyx_event(event)
        ),
    }


def _get_webhook_db_connection():
    """
    Import lazily to avoid an app/service circular import while
    app.py is loading.
    """

    from app import get_db_connection

    return get_db_connection()


def _resolve_sms_assignment(cursor, routing_phone):
    phone_digits = _phone_digits(routing_phone)

    if not phone_digits:
        return None

    cursor.execute("""
        SELECT
            sms_phone_number_id,
            spa_id,
            business_unit_id,
            provider,
            phone_number
        FROM sms_phone_numbers
        WHERE provider = 'telnyx'
          AND is_active = TRUE
          AND REGEXP_REPLACE(
                phone_number,
                '[^0-9]',
                '',
                'g'
              ) = %s
        ORDER BY
            is_default DESC,
            sms_phone_number_id
        LIMIT 2
    """, (phone_digits,))

    rows = cursor.fetchall()

    if len(rows) > 1:
        raise RuntimeError(
            "Multiple active Telnyx assignments match "
            "the same routing phone number."
        )

    if not rows:
        return None

    row = rows[0]

    return {
        "sms_phone_number_id": row[0],
        "spa_id": row[1],
        "business_unit_id": row[2],
        "provider": row[3],
        "phone_number": row[4],
    }


def record_verified_telnyx_event(
    event,
    *,
    connection=None,
):
    """
    Idempotently record one verified Telnyx event.

    When a connection is supplied, the caller owns transaction
    control. Production requests use an internally managed
    connection and commit only after the insert succeeds.
    """

    metadata = extract_telnyx_event_metadata(event)

    owns_connection = connection is None

    if owns_connection:
        connection = _get_webhook_db_connection()

    cursor = connection.cursor()

    try:
        assignment = _resolve_sms_assignment(
            cursor,
            metadata["routing_phone"],
        )

        if assignment:
            spa_id = assignment["spa_id"]
            business_unit_id = assignment[
                "business_unit_id"
            ]
            sms_phone_number_id = assignment[
                "sms_phone_number_id"
            ]
            processing_status = "verified"
        else:
            spa_id = None
            business_unit_id = None
            sms_phone_number_id = None
            processing_status = "unrouted"

        cursor.execute("""
            INSERT INTO telnyx_webhook_log (
                spa_id,
                business_unit_id,
                sms_phone_number_id,
                sms_message_id,
                provider,
                event_type,
                brand_id,
                campaign_id,
                phone_number,
                telnyx_event_id,
                payload_json,
                is_processed,
                processing_status,
                error_message,
                provider_message_id,
                sender_phone,
                receiving_phone,
                messaging_profile_id,
                delivery_attempt,
                event_occurred_at,
                signature_verified,
                receive_count,
                last_received_at
            )
            VALUES (
                %s, %s, %s, NULL, 'telnyx',
                %s, %s, %s, %s, %s,
                %s::jsonb, FALSE, %s, NULL,
                %s, %s, %s, %s, %s, %s,
                TRUE, 1, CURRENT_TIMESTAMP
            )
            ON CONFLICT (telnyx_event_id)
            WHERE telnyx_event_id IS NOT NULL
            DO UPDATE SET
                receive_count =
                    telnyx_webhook_log.receive_count + 1,
                last_received_at = CURRENT_TIMESTAMP,
                signature_verified = TRUE
            RETURNING
                webhook_log_id,
                receive_count,
                processing_status,
                spa_id,
                business_unit_id,
                sms_phone_number_id
        """, (
            spa_id,
            business_unit_id,
            sms_phone_number_id,
            metadata["event_type"],
            metadata["brand_id"],
            metadata["campaign_id"],
            metadata["routing_phone"],
            metadata["event_id"],
            json.dumps(
                metadata["sanitized_payload"],
                separators=(",", ":"),
            ),
            processing_status,
            metadata["provider_message_id"],
            metadata["sender_phone"],
            metadata["receiving_phone"],
            metadata["messaging_profile_id"],
            metadata["delivery_attempt"],
            metadata["event_occurred_at"],
        ))

        row = cursor.fetchone()

        if owns_connection:
            connection.commit()

        return {
            "webhook_log_id": row[0],
            "receive_count": row[1],
            "processing_status": row[2],
            "spa_id": row[3],
            "business_unit_id": row[4],
            "sms_phone_number_id": row[5],
            "duplicate": row[1] > 1,
        }

    except Exception:
        if owns_connection:
            connection.rollback()

        raise

    finally:
        cursor.close()

        if owns_connection:
            connection.close()



def process_telnyx_webhook():
    """
    Authenticate and validate a Telnyx messaging webhook.

    Database logging and event processing are added separately
    after this verification boundary is locally validated.
    """

    raw_body = request.get_data(
        cache=True,
        as_text=False,
    )

    signature_value = request.headers.get(
        "telnyx-signature-ed25519"
    )
    timestamp_value = request.headers.get(
        "telnyx-timestamp"
    )

    try:
        verify_telnyx_webhook_signature(
            raw_body=raw_body,
            signature_value=signature_value,
            timestamp_value=timestamp_value,
            public_key_value=os.getenv(
                "TELNYX_PUBLIC_KEY"
            ),
        )

    except TelnyxWebhookConfigurationError:
        print(
            "[TELNYX WEBHOOK UNAVAILABLE]",
            {
                "reason":
                    "Webhook verification is not configured."
            },
            flush=True,
        )

        return jsonify({
            "success": False,
            "error": "Webhook verification unavailable.",
        }), 503

    except TelnyxWebhookVerificationError as error:
        print(
            "[TELNYX WEBHOOK REJECTED]",
            {
                "reason": str(error),
            },
            flush=True,
        )

        return jsonify({
            "success": False,
            "error": "Webhook authentication failed.",
        }), 401

    try:
        event = parse_telnyx_event(raw_body)

    except ValueError as error:
        print(
            "[TELNYX WEBHOOK REJECTED]",
            {
                "reason": str(error),
            },
            flush=True,
        )

        return jsonify({
            "success": False,
            "error": "Invalid webhook payload.",
        }), 400

    event_data = event["data"]

    try:
        receipt = record_verified_telnyx_event(
            event
        )

    except Exception as error:
        print(
            "[TELNYX WEBHOOK STORAGE ERROR]",
            {
                "event_id": event_data["id"],
                "event_type": event_data["event_type"],
                "error_type": type(error).__name__,
            },
            flush=True,
        )

        return jsonify({
            "success": False,
            "error": "Webhook storage failed.",
        }), 500

    print(
        "[TELNYX WEBHOOK VERIFIED]",
        {
            "event_id": event_data["id"],
            "event_type": event_data["event_type"],
            "duplicate": receipt["duplicate"],
            "routed": receipt["spa_id"] is not None,
            "processing_status": receipt[
                "processing_status"
            ],
        },
        flush=True,
    )

    return "", 204
