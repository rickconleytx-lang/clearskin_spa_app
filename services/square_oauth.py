"""
Square OAuth helpers for Peach Suite Pro.

Initial rollout:
- production seller OAuth code flow
- server-side token handling only
- AES-256-GCM encrypted token storage
- workspace/environment-bound authenticated encryption
- live Square writes remain separately disabled

No OAuth token should ever be logged, displayed, or stored
in plaintext in the PSP database.
"""

import base64
import os
import secrets
from datetime import datetime
from urllib.parse import urlencode

import requests

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SquareOAuthError(RuntimeError):
    """Raised when Square OAuth cannot be handled safely."""


SQUARE_PRODUCTION_AUTHORIZE_URL = (
    "https://connect.squareup.com/oauth2/authorize"
)

SQUARE_PRODUCTION_TOKEN_URL = (
    "https://connect.squareup.com/oauth2/token"
)


# Least-privilege permissions for the PSP Square V2 scope
# that exists today:
#
# - merchant/location verification
# - customer read/write synchronization
# - catalog read/write synchronization
# - payment retrieval
# - order retrieval for reconciliation
#
# PSP does NOT request PAYMENTS_WRITE here.
DEFAULT_PRODUCTION_SCOPES = (
    "MERCHANT_PROFILE_READ",
    "CUSTOMERS_READ",
    "CUSTOMERS_WRITE",
    "ITEMS_READ",
    "ITEMS_WRITE",
    "PAYMENTS_READ",
    "ORDERS_READ",
)


_ENCRYPTION_VERSION = "v1"

_TOKEN_KINDS = {
    "access",
    "refresh",
}


def _require_text(
    value,
    field_name,
):
    value = str(
        value or ""
    ).strip()

    if not value:
        raise SquareOAuthError(
            f"{field_name} is required."
        )

    return value


def _b64encode(
    value,
):
    return (
        base64.urlsafe_b64encode(
            value
        )
        .decode("ascii")
        .rstrip("=")
    )


def _b64decode(
    value,
):
    value = str(
        value or ""
    ).strip()

    padding = (
        "="
        * (-len(value) % 4)
    )

    try:
        return (
            base64.urlsafe_b64decode(
                value + padding
            )
        )

    except Exception as exc:
        raise SquareOAuthError(
            "Encrypted Square OAuth data "
            "is not valid Base64."
        ) from exc


def generate_encryption_key():
    """
    Generate a new AES-256-GCM key encoded for an
    environment variable.

    This helper does not persist the key anywhere.
    """
    key = AESGCM.generate_key(
        bit_length=256
    )

    return _b64encode(
        key
    )


def decode_encryption_key(
    encoded_key,
):
    encoded_key = _require_text(
        encoded_key,
        "Square OAuth encryption key",
    )

    key = _b64decode(
        encoded_key
    )

    if len(key) != 32:
        raise SquareOAuthError(
            "Square OAuth encryption key "
            "must decode to exactly 32 bytes."
        )

    return key


def get_encryption_key():
    """
    Load the PSP Square OAuth encryption key.

    The raw key belongs only in server environment
    variables, never Git or the database.
    """
    encoded_key = os.environ.get(
        "SQUARE_OAUTH_ENCRYPTION_KEY",
        "",
    )

    return decode_encryption_key(
        encoded_key
    )


def _token_aad(
    *,
    spa_id,
    business_unit_id,
    environment,
    token_kind,
):
    """
    Authenticated associated data binds an encrypted
    credential to one PSP workspace, Square environment,
    and token type.

    A ciphertext copied to another workspace or token
    field will therefore fail authenticated decryption.
    """
    try:
        spa_id = int(
            spa_id
        )

        business_unit_id = int(
            business_unit_id
        )

    except (TypeError, ValueError) as exc:
        raise SquareOAuthError(
            "Square OAuth workspace IDs "
            "must be integers."
        ) from exc

    environment = str(
        environment or ""
    ).strip().lower()

    if environment not in {
        "sandbox",
        "production",
    }:
        raise SquareOAuthError(
            "Square OAuth environment must be "
            "sandbox or production."
        )

    token_kind = str(
        token_kind or ""
    ).strip().lower()

    if token_kind not in _TOKEN_KINDS:
        raise SquareOAuthError(
            "Square OAuth token kind must be "
            "access or refresh."
        )

    value = (
        "peach-suite-pro|square-oauth|"
        f"spa:{spa_id}|"
        f"business-unit:{business_unit_id}|"
        f"environment:{environment}|"
        f"token:{token_kind}|"
        f"version:{_ENCRYPTION_VERSION}"
    )

    return value.encode(
        "utf-8"
    )


def encrypt_token(
    token,
    *,
    spa_id,
    business_unit_id,
    environment,
    token_kind,
    encryption_key=None,
):
    """
    Encrypt one Square OAuth credential with
    AES-256-GCM.

    Stored format:
        v1.<nonce>.<ciphertext+auth-tag>
    """
    token = _require_text(
        token,
        "Square OAuth token",
    )

    key = (
        encryption_key
        if encryption_key is not None
        else get_encryption_key()
    )

    if not isinstance(
        key,
        bytes,
    ):
        raise SquareOAuthError(
            "Square OAuth encryption key "
            "must be bytes."
        )

    if len(key) != 32:
        raise SquareOAuthError(
            "Square OAuth encryption key "
            "must be exactly 32 bytes."
        )

    nonce = secrets.token_bytes(
        12
    )

    aad = _token_aad(
        spa_id=spa_id,
        business_unit_id=business_unit_id,
        environment=environment,
        token_kind=token_kind,
    )

    ciphertext = AESGCM(
        key
    ).encrypt(
        nonce,
        token.encode("utf-8"),
        aad,
    )

    return ".".join((
        _ENCRYPTION_VERSION,
        _b64encode(nonce),
        _b64encode(ciphertext),
    ))


def decrypt_token(
    ciphertext_value,
    *,
    spa_id,
    business_unit_id,
    environment,
    token_kind,
    encryption_key=None,
):
    """
    Decrypt and authenticate one Square OAuth credential.
    """
    ciphertext_value = _require_text(
        ciphertext_value,
        "Encrypted Square OAuth token",
    )

    parts = ciphertext_value.split(
        "."
    )

    if (
        len(parts) != 3
        or parts[0] != _ENCRYPTION_VERSION
    ):
        raise SquareOAuthError(
            "Encrypted Square OAuth token "
            "has an unsupported format."
        )

    nonce = _b64decode(
        parts[1]
    )

    ciphertext = _b64decode(
        parts[2]
    )

    if len(nonce) != 12:
        raise SquareOAuthError(
            "Encrypted Square OAuth nonce "
            "has an invalid length."
        )

    key = (
        encryption_key
        if encryption_key is not None
        else get_encryption_key()
    )

    if not isinstance(
        key,
        bytes,
    ):
        raise SquareOAuthError(
            "Square OAuth encryption key "
            "must be bytes."
        )

    if len(key) != 32:
        raise SquareOAuthError(
            "Square OAuth encryption key "
            "must be exactly 32 bytes."
        )

    aad = _token_aad(
        spa_id=spa_id,
        business_unit_id=business_unit_id,
        environment=environment,
        token_kind=token_kind,
    )

    try:
        plaintext = AESGCM(
            key
        ).decrypt(
            nonce,
            ciphertext,
            aad,
        )

    except InvalidTag as exc:
        raise SquareOAuthError(
            "Square OAuth token authentication failed. "
            "The ciphertext, encryption key, workspace, "
            "environment, or token type does not match."
        ) from exc

    try:
        token = plaintext.decode(
            "utf-8"
        )

    except UnicodeDecodeError as exc:
        raise SquareOAuthError(
            "Decrypted Square OAuth token "
            "is not valid UTF-8."
        ) from exc

    return _require_text(
        token,
        "Decrypted Square OAuth token",
    )


def get_production_application_id():
    return _require_text(
        os.environ.get(
            "SQUARE_PRODUCTION_APPLICATION_ID",
            "",
        ),
        "Square production application ID",
    )


def get_production_application_secret():
    return _require_text(
        os.environ.get(
            "SQUARE_PRODUCTION_APPLICATION_SECRET",
            "",
        ),
        "Square production application secret",
    )


def get_production_redirect_uri():
    return _require_text(
        os.environ.get(
            "SQUARE_PRODUCTION_REDIRECT_URI",
            "",
        ),
        "Square production redirect URI",
    )


def build_production_authorization_url(
    *,
    state,
    application_id=None,
    scopes=None,
):
    """
    Build the Square-hosted seller authorization URL.

    The caller must generate and retain the state value
    in the authenticated PSP session and verify it on
    callback.
    """
    state = _require_text(
        state,
        "Square OAuth state",
    )

    application_id = (
        application_id
        or get_production_application_id()
    )

    application_id = _require_text(
        application_id,
        "Square production application ID",
    )

    if scopes is None:
        scopes = (
            DEFAULT_PRODUCTION_SCOPES
        )

    clean_scopes = []

    for scope in scopes:
        scope = str(
            scope or ""
        ).strip()

        if scope:
            clean_scopes.append(
                scope
            )

    if not clean_scopes:
        raise SquareOAuthError(
            "At least one Square OAuth scope "
            "is required."
        )

    query = urlencode({
        "client_id": application_id,
        "scope": " ".join(
            clean_scopes
        ),
        "session": "false",
        "state": state,
    })

    return (
        SQUARE_PRODUCTION_AUTHORIZE_URL
        + "?"
        + query
    )


def _oauth_headers():
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    api_version = os.environ.get(
        "SQUARE_API_VERSION",
        "",
    ).strip()

    if api_version:
        headers[
            "Square-Version"
        ] = api_version

    return headers


def _safe_oauth_error_detail(
    data,
):
    if not isinstance(
        data,
        dict,
    ):
        return ""

    errors = (
        data.get("errors")
        or []
    )

    if not errors:
        return ""

    first_error = (
        errors[0]
        or {}
    )

    return str(
        first_error.get("detail")
        or first_error.get("code")
        or ""
    ).strip()


def _oauth_post(
    payload,
    *,
    timeout=20,
):
    """
    POST to Square ObtainToken.

    Never include returned token values in raised errors.
    """
    try:
        response = requests.post(
            SQUARE_PRODUCTION_TOKEN_URL,
            headers=_oauth_headers(),
            json=payload,
            timeout=timeout,
        )

    except requests.RequestException as exc:
        raise SquareOAuthError(
            "Unable to contact Square OAuth."
        ) from exc

    try:
        data = response.json()

    except ValueError:
        data = {}

    if not response.ok:
        detail = _safe_oauth_error_detail(
            data
        )

        message = (
            "Square OAuth request failed "
            f"with HTTP {response.status_code}."
        )

        if detail:
            message += (
                " "
                + detail
            )

        raise SquareOAuthError(
            message
        )

    if not isinstance(
        data,
        dict,
    ):
        raise SquareOAuthError(
            "Square OAuth returned an invalid response."
        )

    return data


def _validate_token_response(
    data,
):
    """
    Validate the fields PSP requires before storing tokens.
    """
    if not isinstance(
        data,
        dict,
    ):
        raise SquareOAuthError(
            "Square OAuth token response "
            "must be an object."
        )

    access_token = _require_text(
        data.get("access_token"),
        "Square OAuth access token",
    )

    refresh_token = _require_text(
        data.get("refresh_token"),
        "Square OAuth refresh token",
    )

    merchant_id = _require_text(
        data.get("merchant_id"),
        "Square OAuth merchant ID",
    )

    expires_at = _require_text(
        data.get("expires_at"),
        "Square OAuth expiration",
    )

    try:
        parsed_expires_at = (
            datetime.fromisoformat(
                expires_at.replace(
                    "Z",
                    "+00:00",
                )
            )
        )

    except ValueError as exc:
        raise SquareOAuthError(
            "Square OAuth expiration timestamp "
            "is invalid."
        ) from exc

    if (
        parsed_expires_at.tzinfo
        is None
    ):
        raise SquareOAuthError(
            "Square OAuth expiration timestamp "
            "must include a timezone."
        )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "merchant_id": merchant_id,
        "expires_at": (
            parsed_expires_at
        ),
        "token_type": str(
            data.get("token_type")
            or ""
        ).strip(),
        "short_lived": bool(
            data.get("short_lived")
            or False
        ),
    }


def exchange_authorization_code(
    authorization_code,
    *,
    application_id=None,
    application_secret=None,
    timeout=20,
):
    """
    Exchange one Square authorization code for seller
    OAuth credentials using the server-side code flow.
    """
    authorization_code = _require_text(
        authorization_code,
        "Square authorization code",
    )

    application_id = (
        application_id
        or get_production_application_id()
    )

    application_secret = (
        application_secret
        or get_production_application_secret()
    )

    payload = {
        "client_id": _require_text(
            application_id,
            "Square production application ID",
        ),
        "client_secret": _require_text(
            application_secret,
            "Square production application secret",
        ),
        "grant_type": "authorization_code",
        "code": authorization_code,
    }

    data = _oauth_post(
        payload,
        timeout=timeout,
    )

    return _validate_token_response(
        data
    )


def refresh_access_token(
    refresh_token,
    *,
    application_id=None,
    application_secret=None,
    redirect_uri=None,
    timeout=20,
):
    """
    Refresh a production seller OAuth access token.

    Square recommends refreshing well before the
    30-day access-token expiration.
    """
    refresh_token = _require_text(
        refresh_token,
        "Square OAuth refresh token",
    )

    application_id = (
        application_id
        or get_production_application_id()
    )

    application_secret = (
        application_secret
        or get_production_application_secret()
    )

    redirect_uri = (
        redirect_uri
        or get_production_redirect_uri()
    )

    payload = {
        "client_id": _require_text(
            application_id,
            "Square production application ID",
        ),
        "client_secret": _require_text(
            application_secret,
            "Square production application secret",
        ),
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "redirect_uri": _require_text(
            redirect_uri,
            "Square production redirect URI",
        ),
    }

    data = _oauth_post(
        payload,
        timeout=timeout,
    )

    return _validate_token_response(
        data
    )
