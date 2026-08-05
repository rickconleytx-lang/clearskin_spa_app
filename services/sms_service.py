import os
import requests



def format_us_phone(phone):
    digits = "".join(ch for ch in str(phone) if ch.isdigit())

    if len(digits) == 10:
        return "+1" + digits

    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits

    if str(phone).startswith("+"):
        return str(phone)

    return phone



################################################
#
#   SEND SMS TELNYX
#
#
######################################################

def send_sms_telnyx(
    from_phone,
    to_phone,
    message_body
):
    api_key = os.getenv("TELNYX_API_KEY")

    if not api_key:
        raise ValueError("Missing TELNYX_API_KEY")

    if not from_phone:
        raise ValueError(
            "Missing explicit Telnyx sender number"
        )

    if not to_phone:
        raise ValueError(
            "Missing SMS recipient number"
        )

    url = "https://api.telnyx.com/v2/messages"

    payload = {
        "from": format_us_phone(from_phone),
        "to": format_us_phone(to_phone),
        "text": message_body
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=15
    )

    try:
        data = response.json()
    except Exception:
        data = {}

    if response.status_code not in (200, 201, 202):
        raise RuntimeError(
            "Telnyx SMS failed with HTTP "
            f"{response.status_code}."
        )

    return data


######################################
#   SEND SMS TO PHONE
######################################


def send_sms(
    to_phone,
    message_body,
    spa_id=None,
    client_id=None,
    message_type="service",
    from_phone=None
):
    if not spa_id:
        raise ValueError(
            "send_sms requires spa_id for SMS compliance verification."
        )

    sms_permissions = get_sms_business_permissions(
        spa_id
    )

    marketing_message_types = {
        "marketing",
        "promotion",
        "promotional",
        "campaign",
        "mass_marketing"
    }

    normalized_message_type = (
        message_type or "service"
    ).strip().lower()

    is_marketing_message = (
        normalized_message_type
        in marketing_message_types
    )

    if is_marketing_message:
        if not sms_permissions[
            "marketing_sms_enabled"
        ]:
            raise PermissionError(
                (
                    "SMS marketing is not approved "
                    "for this business."
                )
            )

    else:
        if not sms_permissions[
            "service_sms_enabled"
        ]:
            raise PermissionError(
                sms_permissions["reason"]
                or "SMS service is currently unavailable."
            )

    provider = os.getenv(
        "SMS_PROVIDER",
        "telnyx"
    ).lower()

    if provider == "telnyx":
        if not from_phone:
            raise ValueError(
                "send_sms requires an explicitly resolved "
                "from_phone."
            )

        return send_sms_telnyx(
            from_phone,
            to_phone,
            message_body
        )

    raise ValueError(
        f"Unsupported SMS_PROVIDER: {provider}"
    )