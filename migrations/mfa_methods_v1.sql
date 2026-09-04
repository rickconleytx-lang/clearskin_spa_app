-- Peach Suite Pro
-- Multi-Method MFA V1
--
-- Adds method-neutral MFA settings plus short-lived
-- verification challenges for SMS and email.
--
-- Existing authenticator enrollment and recovery-code
-- tables remain unchanged.
--
-- Raw SMS/email verification codes are NEVER stored.
-- Application code stores only keyed HMAC-SHA256 hashes.

CREATE TABLE mfa_user_settings (

    mfa_user_setting_id SERIAL PRIMARY KEY,

    user_id INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    active_method VARCHAR(20),

    enabled_at TIMESTAMPTZ,

    last_recommended_at TIMESTAMPTZ,

    reminder_snoozed_until TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT mfa_user_settings_user_unique
        UNIQUE (user_id),

    CONSTRAINT mfa_user_settings_method_check
        CHECK (
            active_method IS NULL
            OR active_method IN (
                'authenticator',
                'sms',
                'email'
            )
        ),

    CONSTRAINT mfa_user_settings_enabled_check
        CHECK (
            (
                active_method IS NULL
                AND enabled_at IS NULL
            )
            OR (
                active_method IS NOT NULL
                AND enabled_at IS NOT NULL
            )
        ),

    CONSTRAINT mfa_user_settings_updated_check
        CHECK (updated_at >= created_at)
);


CREATE INDEX mfa_user_settings_active_method_idx
    ON mfa_user_settings (
        active_method
    )
    WHERE active_method IS NOT NULL;


CREATE TABLE mfa_verification_challenges (

    mfa_verification_challenge_id SERIAL PRIMARY KEY,

    user_id INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    method VARCHAR(20) NOT NULL,

    purpose VARCHAR(30) NOT NULL,

    code_hash CHAR(64) NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    expires_at TIMESTAMPTZ NOT NULL,

    delivery_sent_at TIMESTAMPTZ,

    used_at TIMESTAMPTZ,

    invalidated_at TIMESTAMPTZ,

    CONSTRAINT mfa_verification_challenges_method_check
        CHECK (
            method IN (
                'sms',
                'email'
            )
        ),

    CONSTRAINT mfa_verification_challenges_purpose_check
        CHECK (
            purpose IN (
                'enrollment',
                'login',
                'method_change'
            )
        ),

    CONSTRAINT mfa_verification_challenges_expires_check
        CHECK (expires_at > created_at),

    CONSTRAINT mfa_verification_challenges_delivery_check
        CHECK (
            delivery_sent_at IS NULL
            OR (
                delivery_sent_at >= created_at
                AND delivery_sent_at <= expires_at
            )
        ),

    CONSTRAINT mfa_verification_challenges_used_check
        CHECK (
            used_at IS NULL
            OR (
                used_at >= created_at
                AND used_at <= expires_at
                AND delivery_sent_at IS NOT NULL
            )
        ),

    CONSTRAINT mfa_verification_challenges_invalidated_check
        CHECK (
            invalidated_at IS NULL
            OR invalidated_at >= created_at
        ),

    CONSTRAINT mfa_verification_challenges_terminal_state_check
        CHECK (
            NOT (
                used_at IS NOT NULL
                AND invalidated_at IS NOT NULL
            )
        )
);


CREATE INDEX mfa_verification_challenges_user_created_idx
    ON mfa_verification_challenges (
        user_id,
        created_at DESC
    );


CREATE INDEX mfa_verification_challenges_active_idx
    ON mfa_verification_challenges (
        user_id,
        method,
        purpose,
        expires_at
    )
    WHERE delivery_sent_at IS NOT NULL
      AND used_at IS NULL
      AND invalidated_at IS NULL;


-- Preserve existing verified Authenticator enrollments as
-- the user's active MFA method. This includes existing
-- Authenticator users without recreating their enrollment.
INSERT INTO mfa_user_settings (
    user_id,
    active_method,
    enabled_at,
    created_at,
    updated_at
)
SELECT
    user_id,
    'authenticator',
    verified_at,
    verified_at,
    verified_at
FROM mfa_authenticators
WHERE verified_at IS NOT NULL
  AND revoked_at IS NULL
ON CONFLICT (user_id) DO NOTHING;


COMMENT ON TABLE mfa_user_settings IS
    'Peach Suite Pro per-user MFA configuration. '
    'The active method may be authenticator, SMS, or email. '
    'Optional-role recommendation timing is stored separately '
    'so users are not prompted on every sign-in.';


COMMENT ON COLUMN mfa_user_settings.active_method IS
    'Currently active login-verification method. A replacement '
    'method is not activated until its enrollment verification succeeds.';


COMMENT ON COLUMN mfa_user_settings.last_recommended_at IS
    'Most recent time an optional-MFA recommendation was shown.';


COMMENT ON COLUMN mfa_user_settings.reminder_snoozed_until IS
    'Optional-MFA recommendations should not be shown again before '
    'this time. NULL means no explicit reminder snooze is active.';


COMMENT ON TABLE mfa_verification_challenges IS
    'Short-lived one-time Peach Suite Pro MFA challenges used only '
    'for SMS and email verification. Authenticator TOTP challenges '
    'continue to use mfa_authenticators.';


COMMENT ON COLUMN mfa_verification_challenges.code_hash IS
    'HMAC-SHA256 hexadecimal hash of the 6-digit verification code '
    'using a server-side MFA verification-code pepper. The raw code '
    'is never stored or written to logs.';


COMMENT ON COLUMN mfa_verification_challenges.delivery_sent_at IS
    'Set only after Telnyx or Mailgun accepts delivery. An unsent '
    'challenge must never be accepted for verification.';


COMMENT ON COLUMN mfa_verification_challenges.used_at IS
    'Set when this one-time challenge successfully verifies the user.';


COMMENT ON COLUMN mfa_verification_challenges.invalidated_at IS
    'Set when an unused challenge is superseded, delivery fails, '
    'expires operationally, or is otherwise revoked.';
