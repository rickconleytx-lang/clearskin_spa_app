-- Peach Suite Pro
-- Forgot Password V1
-- Secure one-time password reset tokens.
--
-- Raw reset tokens are NEVER stored.
-- Application code stores only a SHA-256 token hash.

CREATE TABLE password_reset_tokens (
    password_reset_token_id SERIAL PRIMARY KEY,

    user_id INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    token_hash CHAR(64) NOT NULL UNIQUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    expires_at TIMESTAMPTZ NOT NULL,

    email_sent_at TIMESTAMPTZ,

    used_at TIMESTAMPTZ,

    invalidated_at TIMESTAMPTZ,

    CONSTRAINT password_reset_tokens_expires_check
        CHECK (expires_at > created_at),

    CONSTRAINT password_reset_tokens_email_sent_check
        CHECK (
            email_sent_at IS NULL
            OR email_sent_at >= created_at
        ),

    CONSTRAINT password_reset_tokens_used_check
        CHECK (
            used_at IS NULL
            OR used_at >= created_at
        ),

    CONSTRAINT password_reset_tokens_invalidated_check
        CHECK (
            invalidated_at IS NULL
            OR invalidated_at >= created_at
        )
);

CREATE INDEX password_reset_tokens_user_created_idx
    ON password_reset_tokens (
        user_id,
        created_at DESC
    );

CREATE INDEX password_reset_tokens_active_expiry_idx
    ON password_reset_tokens (
        expires_at
    )
    WHERE used_at IS NULL
      AND invalidated_at IS NULL;

COMMENT ON TABLE password_reset_tokens IS
    'One-time Peach Suite Pro password reset tokens. '
    'Only cryptographic token hashes are stored.';

COMMENT ON COLUMN password_reset_tokens.token_hash IS
    'SHA-256 hexadecimal hash of the raw reset token. '
    'The raw token exists only in the reset URL sent to the user.';

COMMENT ON COLUMN password_reset_tokens.email_sent_at IS
    'Set only after the password reset email is accepted by the mail provider.';

COMMENT ON COLUMN password_reset_tokens.used_at IS
    'Set when this token successfully resets the account password.';

COMMENT ON COLUMN password_reset_tokens.invalidated_at IS
    'Set when this token is revoked without being used.';
