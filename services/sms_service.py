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





def send_sms_telnyx(to_phone, message_body):
    api_key = os.getenv("TELNYX_API_KEY")
    from_number = os.getenv("TELNYX_FROM_NUMBER")

    if not api_key:
        raise ValueError("Missing TELNYX_API_KEY")

    if not from_number:
        raise ValueError("Missing TELNYX_FROM_NUMBER")

    url = "https://api.telnyx.com/v2/messages"

    payload = {
        "from": from_number,
        "to": format_us_phone(to_phone),
        "text": message_body
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }


    print("TELNYX PAYLOAD:", payload)    

    response = requests.post(url, json=payload, headers=headers, timeout=15)

    try:
        data = response.json()
    except Exception:
        data = {"raw_response": response.text}

    if response.status_code not in (200, 201, 202):
        raise Exception(f"Telnyx SMS failed: {data}")

    return data




######################################
#   SEND SMS TO PHONE
#####################################




def send_sms(to_phone, message_body, spa_id=None, client_id=None, message_type="manual"):
    provider = os.getenv("SMS_PROVIDER", "telnyx").lower()

    if provider == "telnyx":
        return send_sms_telnyx(to_phone, message_body)

    raise ValueError(f"Unsupported SMS_PROVIDER: {provider}")
