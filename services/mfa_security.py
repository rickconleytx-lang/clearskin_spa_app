"""
Peach Suite Pro authenticator-app MFA security helpers.

Security model:
- TOTP is the primary second factor.
- TOTP secrets are encrypted with AES-256-GCM.
- MFA encryption uses its own environment key.
- Recovery codes are high-entropy, one-time credentials.
- Only keyed recovery-code hashes are stored.
- Raw TOTP secrets and recovery codes must never be logged.
"""

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from urllib.parse import quote, urlencode

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class MFAError(RuntimeError):
    """Raised when PSP MFA material cannot be handled safely."""


_ENCRYPTION_VERSION = "v1"
_RECOVERY_HASH_VERSION = "v1"

TOTP_DIGITS = 6
TOTP_PERIOD_SECONDS = 30
TOTP_SECRET_BYTES = 20
TOTP_ALLOWED_DRIFT_STEPS = 1

RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_HEX_LENGTH = 20


def _require_text(value, field_name):
    value = str(value or "").strip()

    if not value:
        raise MFAError(
            f"{field_name} is required."
        )

    return value


def _require_user_id(user_id):
    try:
        user_id = int(user_id)

    except (TypeError, ValueError) as exc:
        raise MFAError(
            "MFA user ID must be an integer."
        ) from exc

    if user_id <= 0:
        raise MFAError(
            "MFA user ID must be positive."
        )

    return user_id


def _b64encode(value):
    return (
        base64.urlsafe_b64encode(value)
        .decode("ascii")
        .rstrip("=")
    )


def _b64decode(value, field_name):
    value = _require_text(
        value,
        field_name,
    )

    padding = "=" * (-len(value) % 4)

    try:
        return base64.urlsafe_b64decode(
            value + padding
        )

    except Exception as exc:
        raise MFAError(
            f"{field_name} is not valid Base64."
        ) from exc


def generate_encryption_key():
    """
    Generate a new AES-256-GCM key suitable for the
    MFA_ENCRYPTION_KEY environment variable.

    This helper does not persist the key anywhere.
    """
    return _b64encode(
        AESGCM.generate_key(
            bit_length=256
        )
    )


def decode_encryption_key(encoded_key):
    key = _b64decode(
        encoded_key,
        "MFA encryption key",
    )

    if len(key) != 32:
        raise MFAError(
            "MFA encryption key must decode to "
            "exactly 32 bytes."
        )

    return key


def get_encryption_key():
    """
    Load the dedicated PSP MFA encryption key.

    The raw key belongs only in server environment
    configuration, never Git or the database.
    """
    return decode_encryption_key(
        os.environ.get(
            "MFA_ENCRYPTION_KEY",
            "",
        )
    )


def generate_recovery_pepper():
    """
    Generate a dedicated 256-bit recovery-code pepper
    suitable for MFA_RECOVERY_PEPPER.

    This helper does not persist the pepper anywhere.
    """
    return _b64encode(
        secrets.token_bytes(32)
    )


def decode_recovery_pepper(encoded_pepper):
    pepper = _b64decode(
        encoded_pepper,
        "MFA recovery pepper",
    )

    if len(pepper) != 32:
        raise MFAError(
            "MFA recovery pepper must decode to "
            "exactly 32 bytes."
        )

    return pepper


def get_recovery_pepper():
    """
    Load the dedicated PSP MFA recovery-code pepper.

    The raw pepper belongs only in server environment
    configuration, never Git or the database.
    """
    return decode_recovery_pepper(
        os.environ.get(
            "MFA_RECOVERY_PEPPER",
            "",
        )
    )


def _encode_totp_secret(raw_secret):
    return (
        base64.b32encode(raw_secret)
        .decode("ascii")
        .rstrip("=")
    )


def _decode_totp_secret(secret):
    secret = (
        _require_text(
            secret,
            "TOTP secret",
        )
        .replace(" ", "")
        .upper()
    )

    padding = "=" * (-len(secret) % 8)

    try:
        raw_secret = base64.b32decode(
            secret + padding,
            casefold=True,
        )

    except Exception as exc:
        raise MFAError(
            "TOTP secret is not valid Base32."
        ) from exc

    if len(raw_secret) != TOTP_SECRET_BYTES:
        raise MFAError(
            "TOTP secret must decode to exactly "
            f"{TOTP_SECRET_BYTES} bytes."
        )

    return raw_secret


def generate_totp_secret():
    """
    Generate one new 160-bit Base32 TOTP secret.

    The caller is responsible for protecting the raw
    secret and encrypting it before persistence.
    """
    return _encode_totp_secret(
        secrets.token_bytes(
            TOTP_SECRET_BYTES
        )
    )


def _totp_aad(user_id):
    user_id = _require_user_id(
        user_id
    )

    value = (
        "peach-suite-pro|mfa-totp|"
        f"user:{user_id}|"
        f"version:{_ENCRYPTION_VERSION}"
    )

    return value.encode(
        "utf-8"
    )


def encrypt_totp_secret(
    secret,
    *,
    user_id,
    encryption_key=None,
):
    """
    Encrypt one TOTP secret with AES-256-GCM.

    Stored format:
        v1.<nonce>.<ciphertext+auth-tag>

    Authenticated associated data binds the ciphertext
    to one PSP user identity.
    """
    raw_secret = _decode_totp_secret(
        secret
    )

    canonical_secret = (
        _encode_totp_secret(
            raw_secret
        )
    )

    key = (
        encryption_key
        if encryption_key is not None
        else get_encryption_key()
    )

    if not isinstance(key, bytes):
        raise MFAError(
            "MFA encryption key must be bytes."
        )

    if len(key) != 32:
        raise MFAError(
            "MFA encryption key must be exactly "
            "32 bytes."
        )

    nonce = secrets.token_bytes(
        12
    )

    ciphertext = AESGCM(
        key
    ).encrypt(
        nonce,
        canonical_secret.encode("ascii"),
        _totp_aad(user_id),
    )

    return ".".join((
        _ENCRYPTION_VERSION,
        _b64encode(nonce),
        _b64encode(ciphertext),
    ))


def decrypt_totp_secret(
    ciphertext_value,
    *,
    user_id,
    encryption_key=None,
):
    """
    Decrypt and authenticate one stored TOTP secret.
    """
    ciphertext_value = _require_text(
        ciphertext_value,
        "Encrypted TOTP secret",
    )

    parts = ciphertext_value.split(
        "."
    )

    if (
        len(parts) != 3
        or parts[0] != _ENCRYPTION_VERSION
    ):
        raise MFAError(
            "Encrypted TOTP secret has an "
            "unsupported format."
        )

    nonce = _b64decode(
        parts[1],
        "Encrypted TOTP nonce",
    )

    ciphertext = _b64decode(
        parts[2],
        "Encrypted TOTP ciphertext",
    )

    if len(nonce) != 12:
        raise MFAError(
            "Encrypted TOTP nonce has an "
            "invalid length."
        )

    key = (
        encryption_key
        if encryption_key is not None
        else get_encryption_key()
    )

    if not isinstance(key, bytes):
        raise MFAError(
            "MFA encryption key must be bytes."
        )

    if len(key) != 32:
        raise MFAError(
            "MFA encryption key must be exactly "
            "32 bytes."
        )

    try:
        plaintext = AESGCM(
            key
        ).decrypt(
            nonce,
            ciphertext,
            _totp_aad(user_id),
        )

    except InvalidTag as exc:
        raise MFAError(
            "TOTP secret authentication failed. "
            "The ciphertext, key, or user identity "
            "does not match."
        ) from exc

    try:
        secret = plaintext.decode(
            "ascii"
        )

    except UnicodeDecodeError as exc:
        raise MFAError(
            "Decrypted TOTP secret is not valid ASCII."
        ) from exc

    raw_secret = _decode_totp_secret(
        secret
    )

    return _encode_totp_secret(
        raw_secret
    )


def _totp_code_for_counter(
    secret,
    counter,
):
    raw_secret = _decode_totp_secret(
        secret
    )

    try:
        counter = int(counter)

    except (TypeError, ValueError) as exc:
        raise MFAError(
            "TOTP counter must be an integer."
        ) from exc

    if counter < 0:
        raise MFAError(
            "TOTP counter cannot be negative."
        )

    message = struct.pack(
        ">Q",
        counter,
    )

    digest = hmac.new(
        raw_secret,
        message,
        hashlib.sha1,
    ).digest()

    offset = digest[-1] & 0x0F

    binary_code = (
        (
            digest[offset] & 0x7F
        ) << 24
        | digest[offset + 1] << 16
        | digest[offset + 2] << 8
        | digest[offset + 3]
    )

    code = (
        binary_code
        % (10 ** TOTP_DIGITS)
    )

    return str(code).zfill(
        TOTP_DIGITS
    )


def _totp_counter(at_time=None):
    if at_time is None:
        timestamp = time.time()

    else:
        try:
            timestamp = float(
                at_time
            )

        except (TypeError, ValueError) as exc:
            raise MFAError(
                "TOTP verification time is invalid."
            ) from exc

    if timestamp < 0:
        raise MFAError(
            "TOTP verification time cannot be negative."
        )

    return (
        int(timestamp)
        // TOTP_PERIOD_SECONDS
    )


def generate_totp_code(
    secret,
    *,
    at_time=None,
):
    """
    Generate the RFC 6238 six-digit TOTP code for tests
    and internal verification.

    Application code must never log the returned code.
    """
    return _totp_code_for_counter(
        secret,
        _totp_counter(
            at_time
        ),
    )


def verify_totp_code(
    secret,
    code,
    *,
    at_time=None,
    allowed_drift_steps=TOTP_ALLOWED_DRIFT_STEPS,
    last_accepted_counter=None,
):
    """
    Verify a TOTP value.

    Returns the accepted TOTP counter on success.
    Returns None on an invalid code.

    last_accepted_counter can be supplied to prevent
    successful replay of an already-used TOTP step.
    """
    code = str(
        code or ""
    ).strip().replace(
        " ",
        "",
    )

    if (
        len(code) != TOTP_DIGITS
        or not code.isdigit()
    ):
        return None

    try:
        allowed_drift_steps = int(
            allowed_drift_steps
        )

    except (TypeError, ValueError) as exc:
        raise MFAError(
            "TOTP drift allowance must be an integer."
        ) from exc

    if (
        allowed_drift_steps < 0
        or allowed_drift_steps > 2
    ):
        raise MFAError(
            "TOTP drift allowance must be between "
            "0 and 2 steps."
        )

    if last_accepted_counter is not None:
        try:
            last_accepted_counter = int(
                last_accepted_counter
            )

        except (TypeError, ValueError) as exc:
            raise MFAError(
                "Last accepted TOTP counter "
                "must be an integer."
            ) from exc

    current_counter = _totp_counter(
        at_time
    )

    offsets = [0]

    for step in range(
        1,
        allowed_drift_steps + 1,
    ):
        offsets.extend(
            (-step, step)
        )

    for offset in offsets:
        candidate_counter = (
            current_counter + offset
        )

        if candidate_counter < 0:
            continue

        if (
            last_accepted_counter is not None
            and candidate_counter
            <= last_accepted_counter
        ):
            continue

        expected_code = (
            _totp_code_for_counter(
                secret,
                candidate_counter,
            )
        )

        if hmac.compare_digest(
            expected_code,
            code,
        ):
            return candidate_counter

    return None


def build_totp_uri(
    secret,
    *,
    account_name,
    issuer="Peach Suite Pro",
):
    """
    Build the standard otpauth URI consumed by
    authenticator applications.
    """
    raw_secret = _decode_totp_secret(
        secret
    )

    canonical_secret = (
        _encode_totp_secret(
            raw_secret
        )
    )

    account_name = _require_text(
        account_name,
        "MFA account name",
    )

    issuer = _require_text(
        issuer,
        "MFA issuer",
    )

    label = quote(
        f"{issuer}:{account_name}",
        safe="",
    )

    query = urlencode({
        "secret": canonical_secret,
        "issuer": issuer,
        "algorithm": "SHA1",
        "digits": TOTP_DIGITS,
        "period": TOTP_PERIOD_SECONDS,
    })

    return (
        f"otpauth://totp/{label}?{query}"
    )


def _normalize_recovery_code(code):
    normalized = (
        str(code or "")
        .strip()
        .replace("-", "")
        .replace(" ", "")
        .upper()
    )

    if (
        len(normalized)
        != RECOVERY_CODE_HEX_LENGTH
        or any(
            character
            not in "0123456789ABCDEF"
            for character in normalized
        )
    ):
        raise MFAError(
            "Recovery code has an invalid format."
        )

    return normalized


def _format_recovery_code(
    normalized_code,
):
    return "-".join(
        normalized_code[index:index + 4]
        for index in range(
            0,
            len(normalized_code),
            4,
        )
    )


def generate_recovery_codes(
    count=RECOVERY_CODE_COUNT,
):
    """
    Generate one display-only recovery-code set.

    Each code has 80 bits of random entropy and is
    returned in groups of four characters for entry.

    The caller must display these only once and persist
    only the keyed hashes.
    """
    try:
        count = int(
            count
        )

    except (TypeError, ValueError) as exc:
        raise MFAError(
            "Recovery-code count must be an integer."
        ) from exc

    if count < 1 or count > 20:
        raise MFAError(
            "Recovery-code count must be between "
            "1 and 20."
        )

    recovery_codes = []
    seen = set()

    while len(recovery_codes) < count:
        normalized_code = (
            secrets.token_hex(10)
            .upper()
        )

        if normalized_code in seen:
            continue

        seen.add(
            normalized_code
        )

        recovery_codes.append(
            _format_recovery_code(
                normalized_code
            )
        )

    return recovery_codes


def hash_recovery_code(
    code,
    *,
    user_id,
    pepper=None,
):
    """
    Produce the keyed hash stored for one recovery code.

    A dedicated server-side pepper prevents a database-only
    compromise from exposing a usable recovery credential.
    """
    normalized_code = (
        _normalize_recovery_code(
            code
        )
    )

    user_id = _require_user_id(
        user_id
    )

    pepper = (
        pepper
        if pepper is not None
        else get_recovery_pepper()
    )

    if not isinstance(
        pepper,
        bytes,
    ):
        raise MFAError(
            "MFA recovery pepper must be bytes."
        )

    if len(pepper) != 32:
        raise MFAError(
            "MFA recovery pepper must be exactly "
            "32 bytes."
        )

    message = (
        "peach-suite-pro|mfa-recovery|"
        f"user:{user_id}|"
        f"code:{normalized_code}|"
        f"version:{_RECOVERY_HASH_VERSION}"
    ).encode(
        "utf-8"
    )

    return hmac.new(
        pepper,
        message,
        hashlib.sha256,
    ).hexdigest()


def verify_recovery_code(
    code,
    stored_hash,
    *,
    user_id,
    pepper=None,
):
    """
    Compare a submitted recovery code to one stored
    keyed hash without exposing the raw credential.
    """
    stored_hash = str(
        stored_hash or ""
    ).strip().lower()

    if (
        len(stored_hash) != 64
        or any(
            character
            not in "0123456789abcdef"
            for character in stored_hash
        )
    ):
        return False

    try:
        candidate_hash = (
            hash_recovery_code(
                code,
                user_id=user_id,
                pepper=pepper,
            )
        )

    except MFAError:
        return False

    return hmac.compare_digest(
        candidate_hash,
        stored_hash,
    )
