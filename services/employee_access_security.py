"""
Peach Suite Pro Employee Access Code security helpers.

Security model:
- Business login identifies the PSP tenant/session.
- Employee Access Code identifies the individual employee.
- Codes are short shared-workstation verification credentials.
- Only dedicated peppered, workspace-bound HMAC hashes are stored.
- Raw Employee Access Codes must never be logged or persisted.
"""

import base64
import hashlib
import hmac
import os
import secrets
import string


class EmployeeAccessSecurityError(RuntimeError):
    """Raised when Employee Access security material is unsafe."""


_ACCESS_CODE_HASH_VERSION = "v1"

ACCESS_CODE_ALLOWED_LENGTHS = (4, 5)
ACCESS_CODE_ALLOWED_CHARACTER_SETS = (
    "numeric",
    "alphanumeric",
)

_NUMERIC_ALPHABET = string.digits
_ALPHANUMERIC_ALPHABET = (
    string.ascii_uppercase
    + string.digits
)


def _require_positive_id(value, field_name):
    try:
        value = int(value)

    except (TypeError, ValueError) as exc:
        raise EmployeeAccessSecurityError(
            f"{field_name} must be an integer."
        ) from exc

    if value <= 0:
        raise EmployeeAccessSecurityError(
            f"{field_name} must be positive."
        )

    return value


def _b64encode(value):
    return (
        base64.urlsafe_b64encode(value)
        .decode("ascii")
        .rstrip("=")
    )


def _b64decode(value, field_name):
    value = str(value or "").strip()

    if not value:
        raise EmployeeAccessSecurityError(
            f"{field_name} is required."
        )

    padding = "=" * (-len(value) % 4)

    try:
        return base64.urlsafe_b64decode(
            value + padding
        )

    except Exception as exc:
        raise EmployeeAccessSecurityError(
            f"{field_name} is not valid Base64."
        ) from exc


def generate_access_code_pepper():
    """
    Generate a dedicated 256-bit pepper suitable for
    EMPLOYEE_ACCESS_CODE_PEPPER.

    This helper does not persist the pepper anywhere.
    """
    return _b64encode(
        secrets.token_bytes(32)
    )


def decode_access_code_pepper(encoded_pepper):
    pepper = _b64decode(
        encoded_pepper,
        "Employee Access Code pepper",
    )

    if len(pepper) != 32:
        raise EmployeeAccessSecurityError(
            "Employee Access Code pepper must decode to "
            "exactly 32 bytes."
        )

    return pepper


def get_access_code_pepper():
    """
    Load the dedicated Employee Access Code pepper.

    The raw pepper belongs only in server environment
    configuration, never Git or the database.
    """
    return decode_access_code_pepper(
        os.environ.get(
            "EMPLOYEE_ACCESS_CODE_PEPPER",
            "",
        )
    )


def normalize_access_code_format(
    code_length,
    code_character_set,
):
    try:
        code_length = int(code_length)

    except (TypeError, ValueError) as exc:
        raise EmployeeAccessSecurityError(
            "Employee Access Code length must be 4 or 5."
        ) from exc

    if code_length not in ACCESS_CODE_ALLOWED_LENGTHS:
        raise EmployeeAccessSecurityError(
            "Employee Access Code length must be 4 or 5."
        )

    code_character_set = str(
        code_character_set or ""
    ).strip().lower()

    if (
        code_character_set
        not in ACCESS_CODE_ALLOWED_CHARACTER_SETS
    ):
        raise EmployeeAccessSecurityError(
            "Employee Access Code character set must be "
            "numeric or alphanumeric."
        )

    return code_length, code_character_set


def normalize_access_code(
    code,
    *,
    code_length,
    code_character_set,
):
    code_length, code_character_set = (
        normalize_access_code_format(
            code_length,
            code_character_set,
        )
    )

    code = str(code or "").strip().upper()

    if len(code) != code_length:
        raise EmployeeAccessSecurityError(
            "Employee Access Code has an invalid length."
        )

    if code_character_set == "numeric":
        valid = all(
            character in _NUMERIC_ALPHABET
            for character in code
        )
    else:
        valid = all(
            character in _ALPHANUMERIC_ALPHABET
            for character in code
        )

    if not valid:
        raise EmployeeAccessSecurityError(
            "Employee Access Code contains invalid characters."
        )

    return code


def generate_access_code(
    *,
    code_length,
    code_character_set,
):
    """
    Generate one cryptographically random Employee Access Code.

    Workspace uniqueness remains authoritative in the database.
    """
    code_length, code_character_set = (
        normalize_access_code_format(
            code_length,
            code_character_set,
        )
    )

    alphabet = (
        _NUMERIC_ALPHABET
        if code_character_set == "numeric"
        else _ALPHANUMERIC_ALPHABET
    )

    return "".join(
        secrets.choice(alphabet)
        for _ in range(code_length)
    )


def hash_access_code(
    code,
    *,
    spa_id,
    business_unit_id,
    code_length,
    code_character_set,
    pepper=None,
):
    """
    Produce the keyed hash stored for one Employee Access Code.

    employee_id is intentionally excluded so the same active
    code hashes identically within one workspace, allowing the
    database uniqueness constraint to prevent duplicate codes.
    """
    spa_id = _require_positive_id(
        spa_id,
        "Employee Access spa ID",
    )

    business_unit_id = _require_positive_id(
        business_unit_id,
        "Employee Access business unit ID",
    )

    normalized_code = normalize_access_code(
        code,
        code_length=code_length,
        code_character_set=code_character_set,
    )

    code_length, code_character_set = (
        normalize_access_code_format(
            code_length,
            code_character_set,
        )
    )

    pepper = (
        pepper
        if pepper is not None
        else get_access_code_pepper()
    )

    if not isinstance(pepper, bytes):
        raise EmployeeAccessSecurityError(
            "Employee Access Code pepper must be bytes."
        )

    if len(pepper) != 32:
        raise EmployeeAccessSecurityError(
            "Employee Access Code pepper must be "
            "exactly 32 bytes."
        )

    message = (
        "peach-suite-pro|employee-access-code|"
        f"spa:{spa_id}|"
        f"business-unit:{business_unit_id}|"
        f"length:{code_length}|"
        f"character-set:{code_character_set}|"
        f"code:{normalized_code}|"
        f"version:{_ACCESS_CODE_HASH_VERSION}"
    ).encode(
        "utf-8"
    )

    return hmac.new(
        pepper,
        message,
        hashlib.sha256,
    ).hexdigest()


def verify_access_code(
    code,
    stored_hash,
    *,
    spa_id,
    business_unit_id,
    code_length,
    code_character_set,
    pepper=None,
):
    """
    Compare a submitted Employee Access Code to one stored
    workspace-bound keyed hash in constant time.
    """
    stored_hash = str(
        stored_hash or ""
    ).strip().lower()

    if (
        len(stored_hash) != 64
        or any(
            character not in "0123456789abcdef"
            for character in stored_hash
        )
    ):
        return False

    try:
        candidate_hash = hash_access_code(
            code,
            spa_id=spa_id,
            business_unit_id=business_unit_id,
            code_length=code_length,
            code_character_set=code_character_set,
            pepper=pepper,
        )

    except EmployeeAccessSecurityError:
        return False

    return hmac.compare_digest(
        candidate_hash,
        stored_hash,
    )
