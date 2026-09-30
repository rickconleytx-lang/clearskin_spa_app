import hashlib
import hmac

from datetime import timedelta

from services.contact_security import (
    ContactSecurityError,
    normalize_user_mobile_phone,
)

from services.mfa_security import (
    MFAError,
    generate_verification_code,
    get_verification_code_pepper,
)


SIGNUP_PHONE_VERIFICATION_CODE_MINUTES = 10
SIGNUP_PHONE_VERIFICATION_RESEND_COOLDOWN_SECONDS = 60
SIGNUP_PHONE_VERIFICATION_MAX_DELIVERIES_PER_HOUR = 3

SIGNUP_PHONE_VERIFICATION_MAX_FAILED_ATTEMPTS = 5
SIGNUP_PHONE_VERIFICATION_FAILURE_WINDOW_MINUTES = 15
SIGNUP_PHONE_VERIFICATION_LOCK_MINUTES = 15

_SIGNUP_PHONE_CODE_HASH_VERSION = 1


class StripeSignupSecurityError(RuntimeError):
    """Raised when pre-Checkout signup verification is invalid."""


def normalize_checkout_signup_token(value):
    token = str(
        value or ""
    ).strip()

    if not token:
        raise StripeSignupSecurityError(
            "Checkout signup token is required."
        )

    if len(token) > 64:
        raise StripeSignupSecurityError(
            "Checkout signup token is invalid."
        )

    return token


def normalize_signup_phone_number(value):
    """
    Normalize the prospective Owner's mobile number using the
    same canonical PSP rule used for permanent user accounts.
    """
    try:
        phone = normalize_user_mobile_phone(value)
    except ContactSecurityError as exc:
        raise StripeSignupSecurityError(
            str(exc)
        ) from exc

    if not phone:
        raise StripeSignupSecurityError(
            "Signup phone number is required."
        )

    return phone


def normalize_signup_phone_verification_code(value):
    code = str(
        value or ""
    ).strip()

    if len(code) != 6 or not code.isdigit():
        raise StripeSignupSecurityError(
            "Verification code must be exactly 6 digits."
        )

    return code


def generate_signup_phone_verification_code():
    """
    Generate one cryptographically random six-digit signup
    verification code using PSP's existing MFA code generator.
    """
    return generate_verification_code()


def hash_signup_phone_verification_code(
    code,
    *,
    checkout_signup_token,
    phone_number,
    pepper=None,
):
    """
    Hash one pre-Checkout phone verification code.

    The code is bound to both the opaque signup token and the
    normalized destination phone number so it cannot be moved
    between signups or reused after the phone number changes.
    """
    code = normalize_signup_phone_verification_code(
        code
    )

    checkout_signup_token = (
        normalize_checkout_signup_token(
            checkout_signup_token
        )
    )

    phone_number = normalize_signup_phone_number(
        phone_number
    )

    pepper = (
        pepper
        if pepper is not None
        else get_verification_code_pepper()
    )

    if not isinstance(pepper, bytes):
        raise StripeSignupSecurityError(
            "Verification-code pepper must be bytes."
        )

    if len(pepper) != 32:
        raise StripeSignupSecurityError(
            "Verification-code pepper must be exactly 32 bytes."
        )

    message = (
        "peach-suite-pro|stripe-checkout-phone-verification|"
        f"signup:{checkout_signup_token}|"
        f"phone:{phone_number}|"
        f"code:{code}|"
        f"version:{_SIGNUP_PHONE_CODE_HASH_VERSION}"
    ).encode("utf-8")

    return hmac.new(
        pepper,
        message,
        hashlib.sha256,
    ).hexdigest()


def verify_signup_phone_verification_code(
    code,
    stored_hash,
    *,
    checkout_signup_token,
    phone_number,
    pepper=None,
):
    """
    Constant-time comparison for one pre-Checkout phone code.
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
        candidate_hash = (
            hash_signup_phone_verification_code(
                code,
                checkout_signup_token=(
                    checkout_signup_token
                ),
                phone_number=phone_number,
                pepper=pepper,
            )
        )

    except (
        StripeSignupSecurityError,
        MFAError,
    ):
        return False

    return hmac.compare_digest(
        candidate_hash,
        stored_hash,
    )


def signup_phone_verification_delivery_limit_state(
    cursor,
    *,
    stripe_checkout_signup_id,
    phone_number,
):
    """
    Enforce PSP's security-code delivery policy for the
    destination phone number across all public signup records.

    Only successfully delivered challenges count toward limits.
    Scoping by phone prevents a new signup record from bypassing
    the resend cooldown or three-deliveries-per-hour protection.
    """
    try:
        signup_id = int(
            stripe_checkout_signup_id
        )
    except (TypeError, ValueError):
        raise StripeSignupSecurityError(
            "Checkout signup is invalid."
        )

    if signup_id <= 0:
        raise StripeSignupSecurityError(
            "Checkout signup is invalid."
        )

    phone_number = normalize_signup_phone_number(
        phone_number
    )

    cursor.execute(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE delivery_sent_at >= (
                    NOW() - INTERVAL '1 hour'
                )
            ),
            MAX(delivery_sent_at),
            MIN(delivery_sent_at) FILTER (
                WHERE delivery_sent_at >= (
                    NOW() - INTERVAL '1 hour'
                )
            ),
            NOW()
        FROM stripe_checkout_phone_verification_challenges
        WHERE phone_number = %s
          AND delivery_sent_at IS NOT NULL
        """,
        (
            phone_number,
        ),
    )

    row = cursor.fetchone()

    if not row:
        raise StripeSignupSecurityError(
            "Signup phone verification delivery limits "
            "could not be determined."
        )

    successful_deliveries = int(
        row[0] or 0
    )

    latest_delivery_at = row[1]
    oldest_hour_delivery_at = row[2]
    now_at = row[3]

    if latest_delivery_at is not None:
        cooldown_elapsed = (
            now_at - latest_delivery_at
        ).total_seconds()

        if (
            cooldown_elapsed
            < SIGNUP_PHONE_VERIFICATION_RESEND_COOLDOWN_SECONDS
        ):
            retry_seconds = max(
                1,
                int(
                    SIGNUP_PHONE_VERIFICATION_RESEND_COOLDOWN_SECONDS
                    - cooldown_elapsed
                )
                + 1,
            )

            return {
                "allowed": False,
                "reason": "cooldown",
                "retry_seconds": retry_seconds,
            }

    if (
        successful_deliveries
        >= SIGNUP_PHONE_VERIFICATION_MAX_DELIVERIES_PER_HOUR
    ):
        if oldest_hour_delivery_at is None:
            raise StripeSignupSecurityError(
                "Signup phone verification hourly limit "
                "state is inconsistent."
            )

        hourly_elapsed = (
            now_at - oldest_hour_delivery_at
        ).total_seconds()

        retry_seconds = max(
            1,
            int(
                (60 * 60) - hourly_elapsed
            )
            + 1,
        )

        return {
            "allowed": False,
            "reason": "hourly_limit",
            "retry_seconds": retry_seconds,
        }

    return {
        "allowed": True,
        "reason": None,
        "retry_seconds": 0,
    }


def reserve_signup_phone_verification_challenge(
    cursor,
    *,
    stripe_checkout_signup_id,
):
    """
    Reserve one short-lived phone verification challenge.

    This function intentionally does not commit or send SMS.
    """
    try:
        signup_id = int(
            stripe_checkout_signup_id
        )
    except (TypeError, ValueError):
        raise StripeSignupSecurityError(
            "Checkout signup is invalid."
        )

    if signup_id <= 0:
        raise StripeSignupSecurityError(
            "Checkout signup is invalid."
        )

    cursor.execute(
        """
        SELECT
            checkout_signup_token,
            owner_phone,
            phone_verified_at,
            phone_verification_locked_until,
            signup_status,
            NOW()
        FROM stripe_checkout_signups
        WHERE stripe_checkout_signup_id = %s
        FOR UPDATE
        """,
        (signup_id,),
    )

    signup = cursor.fetchone()

    if not signup:
        raise StripeSignupSecurityError(
            "Checkout signup is no longer available."
        )

    (
        checkout_signup_token,
        owner_phone,
        phone_verified_at,
        locked_until,
        signup_status,
        now_at,
    ) = signup

    if signup_status != "pending":
        raise StripeSignupSecurityError(
            "Phone verification is no longer available "
            "for this signup."
        )

    phone_number = normalize_signup_phone_number(
        owner_phone
    )

    if phone_verified_at is not None:
        return {
            "allowed": False,
            "reason": "already_verified",
            "retry_seconds": 0,
        }

    if (
        locked_until is not None
        and locked_until > now_at
    ):
        retry_seconds = max(
            1,
            int(
                (
                    locked_until - now_at
                ).total_seconds()
            )
            + 1,
        )

        return {
            "allowed": False,
            "reason": "locked",
            "retry_seconds": retry_seconds,
        }

    limit_state = (
        signup_phone_verification_delivery_limit_state(
            cursor,
            stripe_checkout_signup_id=signup_id,
            phone_number=phone_number,
        )
    )

    if not limit_state["allowed"]:
        return limit_state

    raw_code = (
        generate_signup_phone_verification_code()
    )

    code_hash = (
        hash_signup_phone_verification_code(
            raw_code,
            checkout_signup_token=(
                checkout_signup_token
            ),
            phone_number=phone_number,
        )
    )

    cursor.execute(
        """
        INSERT INTO stripe_checkout_phone_verification_challenges (
            stripe_checkout_signup_id,
            phone_number,
            code_hash,
            expires_at
        )
        VALUES (
            %s,
            %s,
            %s,
            NOW() + (
                %s * INTERVAL '1 minute'
            )
        )
        RETURNING
            stripe_checkout_phone_verification_challenge_id,
            expires_at
        """,
        (
            signup_id,
            phone_number,
            code_hash,
            SIGNUP_PHONE_VERIFICATION_CODE_MINUTES,
        ),
    )

    challenge = cursor.fetchone()

    if not challenge:
        raise StripeSignupSecurityError(
            "Signup phone verification challenge "
            "reservation failed."
        )

    return {
        "allowed": True,
        "reason": None,
        "retry_seconds": 0,
        "stripe_checkout_phone_verification_challenge_id": (
            challenge[0]
        ),
        "raw_code": raw_code,
        "expires_at": challenge[1],
        "phone_number": phone_number,
    }


def finalize_signup_phone_verification_delivery(
    cursor,
    *,
    stripe_checkout_signup_id,
    stripe_checkout_phone_verification_challenge_id,
):
    """
    Mark a reserved challenge delivered only after the SMS
    provider has accepted the verification message.
    """
    signup_id = int(
        stripe_checkout_signup_id
    )

    challenge_id = int(
        stripe_checkout_phone_verification_challenge_id
    )

    cursor.execute(
        """
        SELECT
            stripe_checkout_signup_id
        FROM stripe_checkout_signups
        WHERE stripe_checkout_signup_id = %s
        FOR UPDATE
        """,
        (signup_id,),
    )

    if not cursor.fetchone():
        raise StripeSignupSecurityError(
            "Checkout signup is no longer available."
        )

    cursor.execute(
        """
        SELECT
            stripe_checkout_phone_verification_challenge_id,
            expires_at,
            delivery_sent_at,
            used_at,
            invalidated_at,
            NOW()
        FROM stripe_checkout_phone_verification_challenges
        WHERE
            stripe_checkout_phone_verification_challenge_id = %s
          AND stripe_checkout_signup_id = %s
        FOR UPDATE
        """,
        (
            challenge_id,
            signup_id,
        ),
    )

    challenge = cursor.fetchone()

    if (
        not challenge
        or challenge[2] is not None
        or challenge[3] is not None
        or challenge[4] is not None
    ):
        raise StripeSignupSecurityError(
            "Signup phone verification challenge "
            "could not be finalized."
        )

    expires_at = challenge[1]
    now_at = challenge[5]

    if expires_at <= now_at:
        cursor.execute(
            """
            UPDATE stripe_checkout_phone_verification_challenges
            SET invalidated_at = NOW()
            WHERE
                stripe_checkout_phone_verification_challenge_id = %s
              AND stripe_checkout_signup_id = %s
              AND delivery_sent_at IS NULL
              AND used_at IS NULL
              AND invalidated_at IS NULL
            """,
            (
                challenge_id,
                signup_id,
            ),
        )

        return False

    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM stripe_checkout_phone_verification_challenges
            WHERE stripe_checkout_signup_id = %s
              AND stripe_checkout_phone_verification_challenge_id > %s
              AND delivery_sent_at IS NOT NULL
        )
        """,
        (
            signup_id,
            challenge_id,
        ),
    )

    newer_delivery_exists = bool(
        cursor.fetchone()[0]
    )

    if newer_delivery_exists:
        cursor.execute(
            """
            UPDATE stripe_checkout_phone_verification_challenges
            SET
                delivery_sent_at = NOW(),
                invalidated_at = COALESCE(
                    invalidated_at,
                    NOW()
                )
            WHERE
                stripe_checkout_phone_verification_challenge_id = %s
              AND stripe_checkout_signup_id = %s
              AND delivery_sent_at IS NULL
              AND used_at IS NULL
              AND expires_at > NOW()
            RETURNING
                stripe_checkout_phone_verification_challenge_id
            """,
            (
                challenge_id,
                signup_id,
            ),
        )

        if not cursor.fetchone():
            raise StripeSignupSecurityError(
                "Superseded signup phone challenge "
                "could not be finalized."
            )

        return False

    cursor.execute(
        """
        UPDATE stripe_checkout_phone_verification_challenges
        SET delivery_sent_at = NOW()
        WHERE
            stripe_checkout_phone_verification_challenge_id = %s
          AND stripe_checkout_signup_id = %s
          AND delivery_sent_at IS NULL
          AND used_at IS NULL
          AND invalidated_at IS NULL
          AND expires_at > NOW()
        RETURNING
            stripe_checkout_phone_verification_challenge_id
        """,
        (
            challenge_id,
            signup_id,
        ),
    )

    if not cursor.fetchone():
        raise StripeSignupSecurityError(
            "Signup phone verification challenge "
            "could not be activated after delivery."
        )

    cursor.execute(
        """
        UPDATE stripe_checkout_phone_verification_challenges
        SET invalidated_at = NOW()
        WHERE stripe_checkout_signup_id = %s
          AND stripe_checkout_phone_verification_challenge_id < %s
          AND used_at IS NULL
          AND invalidated_at IS NULL
        """,
        (
            signup_id,
            challenge_id,
        ),
    )

    return True


def invalidate_unsent_signup_phone_verification_challenge(
    cursor,
    *,
    stripe_checkout_signup_id,
    stripe_checkout_phone_verification_challenge_id,
):
    """
    Invalidate a reserved signup challenge whose SMS was not
    successfully accepted by the provider.
    """
    signup_id = int(
        stripe_checkout_signup_id
    )

    challenge_id = int(
        stripe_checkout_phone_verification_challenge_id
    )

    cursor.execute(
        """
        UPDATE stripe_checkout_phone_verification_challenges
        SET invalidated_at = NOW()
        WHERE
            stripe_checkout_phone_verification_challenge_id = %s
          AND stripe_checkout_signup_id = %s
          AND delivery_sent_at IS NULL
          AND used_at IS NULL
          AND invalidated_at IS NULL
        RETURNING
            stripe_checkout_phone_verification_challenge_id
        """,
        (
            challenge_id,
            signup_id,
        ),
    )

    return cursor.fetchone() is not None


def verify_signup_phone_verification_challenge(
    cursor,
    *,
    stripe_checkout_signup_id,
    verification_code,
):
    """
    Verify the newest active pre-Checkout phone challenge.

    Failed attempts use PSP's standard security pattern:
      - 5 failures
      - within a 15-minute window
      - causes a 15-minute lockout

    The signup row is locked so verification attempts for the
    same signup are serialized transactionally.
    """
    try:
        signup_id = int(
            stripe_checkout_signup_id
        )
    except (TypeError, ValueError):
        raise StripeSignupSecurityError(
            "Checkout signup is invalid."
        )

    if signup_id <= 0:
        raise StripeSignupSecurityError(
            "Checkout signup is invalid."
        )

    cursor.execute(
        """
        SELECT
            checkout_signup_token,
            owner_phone,
            phone_verified_at,
            phone_verification_failed_count,
            phone_verification_window_started_at,
            phone_verification_last_failed_at,
            phone_verification_locked_until,
            signup_status,
            NOW()
        FROM stripe_checkout_signups
        WHERE stripe_checkout_signup_id = %s
        FOR UPDATE
        """,
        (signup_id,),
    )

    signup = cursor.fetchone()

    if not signup:
        raise StripeSignupSecurityError(
            "Checkout signup is no longer available."
        )

    (
        checkout_signup_token,
        owner_phone,
        phone_verified_at,
        failed_count,
        window_started_at,
        last_failed_at,
        locked_until,
        signup_status,
        now_at,
    ) = signup

    if signup_status != "pending":
        raise StripeSignupSecurityError(
            "Phone verification is no longer available "
            "for this signup."
        )

    phone_number = normalize_signup_phone_number(
        owner_phone
    )

    if phone_verified_at is not None:
        return {
            "verified": True,
            "reason": "already_verified",
            "retry_seconds": 0,
            "attempts_remaining": (
                SIGNUP_PHONE_VERIFICATION_MAX_FAILED_ATTEMPTS
            ),
        }

    if (
        locked_until is not None
        and locked_until > now_at
    ):
        retry_seconds = max(
            1,
            int(
                (
                    locked_until - now_at
                ).total_seconds()
            )
            + 1,
        )

        return {
            "verified": False,
            "reason": "locked",
            "retry_seconds": retry_seconds,
            "attempts_remaining": 0,
        }

    cursor.execute(
        """
        SELECT
            stripe_checkout_phone_verification_challenge_id,
            code_hash
        FROM stripe_checkout_phone_verification_challenges
        WHERE stripe_checkout_signup_id = %s
          AND phone_number = %s
          AND delivery_sent_at IS NOT NULL
          AND used_at IS NULL
          AND invalidated_at IS NULL
          AND expires_at > NOW()
        ORDER BY
            delivery_sent_at DESC,
            stripe_checkout_phone_verification_challenge_id DESC
        LIMIT 1
        FOR UPDATE
        """,
        (
            signup_id,
            phone_number,
        ),
    )

    challenge = cursor.fetchone()

    if not challenge:
        return {
            "verified": False,
            "reason": "challenge_unavailable",
            "retry_seconds": 0,
            "attempts_remaining": max(
                0,
                (
                    SIGNUP_PHONE_VERIFICATION_MAX_FAILED_ATTEMPTS
                    - int(failed_count or 0)
                ),
            ),
        }

    challenge_id = challenge[0]
    stored_hash = challenge[1]

    code_matches = (
        verify_signup_phone_verification_code(
            verification_code,
            stored_hash,
            checkout_signup_token=(
                checkout_signup_token
            ),
            phone_number=phone_number,
        )
    )

    if code_matches:
        cursor.execute(
            """
            UPDATE stripe_checkout_phone_verification_challenges
            SET used_at = NOW()
            WHERE
                stripe_checkout_phone_verification_challenge_id = %s
              AND stripe_checkout_signup_id = %s
              AND phone_number = %s
              AND delivery_sent_at IS NOT NULL
              AND used_at IS NULL
              AND invalidated_at IS NULL
              AND expires_at > NOW()
            RETURNING
                stripe_checkout_phone_verification_challenge_id
            """,
            (
                challenge_id,
                signup_id,
                phone_number,
            ),
        )

        if not cursor.fetchone():
            raise StripeSignupSecurityError(
                "Signup phone verification challenge "
                "could not be completed."
            )

        # Any other unused challenge for this signup becomes
        # unusable once the phone number has been verified.
        cursor.execute(
            """
            UPDATE stripe_checkout_phone_verification_challenges
            SET invalidated_at = NOW()
            WHERE stripe_checkout_signup_id = %s
              AND stripe_checkout_phone_verification_challenge_id <> %s
              AND used_at IS NULL
              AND invalidated_at IS NULL
            """,
            (
                signup_id,
                challenge_id,
            ),
        )

        cursor.execute(
            """
            UPDATE stripe_checkout_signups
            SET
                phone_verified_at = NOW(),
                phone_verification_failed_count = 0,
                phone_verification_window_started_at = NULL,
                phone_verification_last_failed_at = NULL,
                phone_verification_locked_until = NULL,
                updated_at = NOW()
            WHERE stripe_checkout_signup_id = %s
              AND signup_status = 'pending'
              AND phone_verified_at IS NULL
            RETURNING phone_verified_at
            """,
            (signup_id,),
        )

        verified_row = cursor.fetchone()

        if not verified_row:
            raise StripeSignupSecurityError(
                "Signup phone verification state "
                "could not be completed."
            )

        return {
            "verified": True,
            "reason": None,
            "retry_seconds": 0,
            "attempts_remaining": (
                SIGNUP_PHONE_VERIFICATION_MAX_FAILED_ATTEMPTS
            ),
            "phone_verified_at": verified_row[0],
        }

    window_expired = bool(
        window_started_at is None
        or window_started_at
        < now_at - timedelta(
            minutes=(
                SIGNUP_PHONE_VERIFICATION_FAILURE_WINDOW_MINUTES
            )
        )
    )

    if window_expired:
        failed_count = 1
        window_started_at = now_at
    else:
        failed_count = int(
            failed_count or 0
        ) + 1

    new_lock = (
        failed_count
        >= SIGNUP_PHONE_VERIFICATION_MAX_FAILED_ATTEMPTS
    )

    if new_lock:
        locked_until = now_at + timedelta(
            minutes=SIGNUP_PHONE_VERIFICATION_LOCK_MINUTES
        )
    else:
        locked_until = None

    cursor.execute(
        """
        UPDATE stripe_checkout_signups
        SET
            phone_verification_failed_count = %s,
            phone_verification_window_started_at = %s,
            phone_verification_last_failed_at = %s,
            phone_verification_locked_until = %s,
            updated_at = NOW()
        WHERE stripe_checkout_signup_id = %s
          AND signup_status = 'pending'
          AND phone_verified_at IS NULL
        """,
        (
            failed_count,
            window_started_at,
            now_at,
            locked_until,
            signup_id,
        ),
    )

    if new_lock:
        # A code that contributed to a lockout must not become
        # usable later if the account is retried after the lock.
        cursor.execute(
            """
            UPDATE stripe_checkout_phone_verification_challenges
            SET invalidated_at = NOW()
            WHERE stripe_checkout_signup_id = %s
              AND used_at IS NULL
              AND invalidated_at IS NULL
            """,
            (signup_id,),
        )

        retry_seconds = max(
            1,
            int(
                (
                    locked_until - now_at
                ).total_seconds()
            ),
        )

        return {
            "verified": False,
            "reason": "locked",
            "retry_seconds": retry_seconds,
            "attempts_remaining": 0,
        }

    return {
        "verified": False,
        "reason": "invalid_code",
        "retry_seconds": 0,
        "attempts_remaining": max(
            0,
            (
                SIGNUP_PHONE_VERIFICATION_MAX_FAILED_ATTEMPTS
                - failed_count
            ),
        ),
    }
