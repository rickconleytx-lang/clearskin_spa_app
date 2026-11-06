"""
Authenticated encryption for attempted login email addresses.

Full addresses are available only through authorized
Master Admin security workflows.

The encryption key is stored in server configuration,
never in Git or PostgreSQL.
"""

import base64
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class LoginEmailCryptoError(ValueError):
    """Invalid or unavailable login-email encryption data."""


_KEY_ENV = "SECURITY_LOGIN_EMAIL_ENCRYPTION_KEY"
_VERSION = "v1"


def _encode(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode(value):
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.b64decode(
            padded,
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise LoginEmailCryptoError(
            "Invalid encrypted email encoding."
        ) from exc


def generate_encryption_key():
    """Generate a key without persisting or logging it."""
    return _encode(AESGCM.generate_key(bit_length=256))


def decode_encryption_key(value):
    if not isinstance(value, str) or not value.strip():
        raise LoginEmailCryptoError(
            "Login email encryption key is unavailable."
        )

    key = _decode(value.strip())

    if len(key) != 32:
        raise LoginEmailCryptoError(
            "Login email encryption key must contain 32 bytes."
        )

    return key


def _get_key(encryption_key):
    if encryption_key is None:
        encryption_key = decode_encryption_key(
            os.environ.get(_KEY_ENV, "")
        )

    if (
        not isinstance(encryption_key, bytes)
        or len(encryption_key) != 32
    ):
        raise LoginEmailCryptoError(
            "Invalid login email encryption key."
        )

    return encryption_key


def _associated_data(system_log_id):
    if (
        isinstance(system_log_id, bool)
        or not isinstance(system_log_id, int)
        or system_log_id <= 0
    ):
        raise LoginEmailCryptoError(
            "A valid security log ID is required."
        )

    return (
        f"psp:security-login-email:v1:{system_log_id}"
    ).encode("ascii")


def encrypt_attempted_email(
    email,
    *,
    system_log_id,
    encryption_key=None,
):
    address = str(email or "").strip().lower()

    if not address or len(address) > 320:
        raise LoginEmailCryptoError(
            "Invalid attempted email length."
        )

    nonce = secrets.token_bytes(12)

    ciphertext = AESGCM(
        _get_key(encryption_key)
    ).encrypt(
        nonce,
        address.encode("utf-8"),
        _associated_data(system_log_id),
    )

    return ".".join((
        _VERSION,
        _encode(nonce),
        _encode(ciphertext),
    ))


def decrypt_attempted_email(
    encrypted_value,
    *,
    system_log_id,
    encryption_key=None,
):
    if not isinstance(encrypted_value, str):
        raise LoginEmailCryptoError(
            "Encrypted email must be text."
        )

    parts = encrypted_value.split(".")

    if len(parts) != 3 or parts[0] != _VERSION:
        raise LoginEmailCryptoError(
            "Unsupported encrypted email format."
        )

    nonce = _decode(parts[1])
    ciphertext = _decode(parts[2])

    if len(nonce) != 12 or len(ciphertext) < 16:
        raise LoginEmailCryptoError(
            "Invalid encrypted email data."
        )

    try:
        plaintext = AESGCM(
            _get_key(encryption_key)
        ).decrypt(
            nonce,
            ciphertext,
            _associated_data(system_log_id),
        )
        return plaintext.decode("utf-8")

    except (InvalidTag, UnicodeDecodeError) as exc:
        raise LoginEmailCryptoError(
            "Encrypted email authentication failed."
        ) from exc
