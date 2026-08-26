-- Peach Suite Pro
-- Authenticator App MFA V1
-- TOTP authenticator enrollment and one-time recovery codes.
--
-- Raw TOTP secrets are NEVER stored in plaintext.
-- Application code stores only AES-256-GCM encrypted TOTP secrets.
--
-- Raw recovery codes are NEVER stored.
-- Application code stores only keyed HMAC-SHA256 recovery-code hashes.

CREATE TABLE mfa_authenticators (

    mfa_authenticator_id SERIAL PRIMARY KEY,

    user_id INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    totp_secret_encrypted TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    verified_at TIMESTAMPTZ,

    revoked_at TIMESTAMPTZ,

    last_accepted_totp_counter BIGINT,

    CONSTRAINT mfa_authenticators_verified_check
        CHECK (
            verified_at IS NULL
            OR verified_at >= created_at
        ),

    CONSTRAINT mfa_authenticators_revoked_check
        CHECK (
            revoked_at IS NULL
            OR revoked_at >= created_at
        ),

    CONSTRAINT mfa_authenticators_counter_check
        CHECK (
            last_accepted_totp_counter IS NULL
            OR last_accepted_totp_counter >= 0
        ),

    CONSTRAINT mfa_authenticators_counter_verified_check
        CHECK (
            last_accepted_totp_counter IS NULL
            OR verified_at IS NOT NULL
        )
);


-- A user may have historical revoked authenticators, but only
-- one current pending or verified authenticator at a time.
CREATE UNIQUE INDEX mfa_authenticators_current_user_idx
    ON mfa_authenticators (
        user_id
    )
    WHERE revoked_at IS NULL;


CREATE INDEX mfa_authenticators_user_history_idx
    ON mfa_authenticators (
        user_id,
        created_at DESC
    );


CREATE TABLE mfa_recovery_codes (

    mfa_recovery_code_id SERIAL PRIMARY KEY,

    mfa_authenticator_id INTEGER NOT NULL
        REFERENCES mfa_authenticators(mfa_authenticator_id)
        ON DELETE CASCADE,

    code_hash CHAR(64) NOT NULL UNIQUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    used_at TIMESTAMPTZ,

    invalidated_at TIMESTAMPTZ,

    CONSTRAINT mfa_recovery_codes_used_check
        CHECK (
            used_at IS NULL
            OR used_at >= created_at
        ),

    CONSTRAINT mfa_recovery_codes_invalidated_check
        CHECK (
            invalidated_at IS NULL
            OR invalidated_at >= created_at
        ),

    CONSTRAINT mfa_recovery_codes_terminal_state_check
        CHECK (
            NOT (
                used_at IS NOT NULL
                AND invalidated_at IS NOT NULL
            )
        )
);


CREATE INDEX mfa_recovery_codes_authenticator_created_idx
    ON mfa_recovery_codes (
        mfa_authenticator_id,
        created_at
    );


CREATE INDEX mfa_recovery_codes_available_idx
    ON mfa_recovery_codes (
        mfa_authenticator_id
    )
    WHERE used_at IS NULL
      AND invalidated_at IS NULL;


COMMENT ON TABLE mfa_authenticators IS
    'Peach Suite Pro authenticator-app MFA enrollments. '
    'TOTP secrets are stored only as authenticated encrypted ciphertext.';


COMMENT ON COLUMN mfa_authenticators.totp_secret_encrypted IS
    'AES-256-GCM encrypted TOTP secret. The raw TOTP secret is never '
    'stored in the database or logs.';


COMMENT ON COLUMN mfa_authenticators.verified_at IS
    'Set only after the user successfully verifies the authenticator '
    'during enrollment.';


COMMENT ON COLUMN mfa_authenticators.revoked_at IS
    'Set when an enrollment is cancelled, reset, replaced, or revoked. '
    'Historical revoked enrollments remain available for audit context.';


COMMENT ON COLUMN mfa_authenticators.last_accepted_totp_counter IS
    'Most recent successfully accepted TOTP time-step counter. Used to '
    'prevent replay of the same authenticator code within its time step.';


COMMENT ON TABLE mfa_recovery_codes IS
    'One-time Peach Suite Pro MFA recovery codes tied to one authenticator '
    'enrollment. Only keyed cryptographic hashes are stored.';


COMMENT ON COLUMN mfa_recovery_codes.code_hash IS
    'HMAC-SHA256 hexadecimal hash of one recovery code using the '
    'server-side MFA recovery pepper. The raw code is displayed once only.';


COMMENT ON COLUMN mfa_recovery_codes.used_at IS
    'Set when this recovery code successfully satisfies an MFA challenge.';


COMMENT ON COLUMN mfa_recovery_codes.invalidated_at IS
    'Set when an unused recovery code is revoked without being used, '
    'including when its authenticator is reset or replaced.';
