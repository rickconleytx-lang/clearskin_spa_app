import os
import requests

MAILGUN_API_KEY = os.environ.get("MAILGUN_API_KEY", "").strip()
MAILGUN_DOMAIN = os.environ.get("MAILGUN_DOMAIN", "").strip()
MAILGUN_FROM = os.environ.get("MAILGUN_FROM", "").strip()

print("Key loaded:", bool(MAILGUN_API_KEY))
print("Key prefix:", MAILGUN_API_KEY[:8] if MAILGUN_API_KEY else "NONE")
print("Domain:", MAILGUN_DOMAIN)
print("From:", MAILGUN_FROM)

response = requests.post(
    f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
    auth=("api", MAILGUN_API_KEY),
    data={
        "from": MAILGUN_FROM,
        "to": ["your_real_email@gmail.com"],
        "subject": "Mailgun Test",
        "text": "If you got this, Mailgun is working with my hidden key!"
    },
    timeout=20
)

print("Status:", response.status_code)
print("Body:", response.text)



