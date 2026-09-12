BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- MASTER ADMIN NATIVE API AUTHENTICATION V1
--
-- Server-side authentication state for the native
-- Master Admin application.
--
-- Raw login-challenge and API-session tokens are NEVER
-- stored in PostgreSQL. Only SHA-256 hexadecimal hashes
-- are persisted.
--
-- Native authentication is intentionally separate from
-- the browser Flask session and browser tab-presence
-- heartbeat.
-- =========================================================


CREATE TABLE IF NOT EXISTS master_admin_api_login_challenges (

    master_admin_api_login_challenge_id BIGSERIAL PRIMARY KEY,

    master_admin_user_id INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    token_hash CHAR(64) NOT NULL,

    password_verified_at TIMESTAMPTZ NOT NULL,

    security_session_version INTEGER NOT NULL,

    password_changed_at_marker VARCHAR(64),

    expires_at TIMESTAMPTZ NOT NULL,

    consumed_at TIMESTAMPTZ,

    revoked_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_master_admin_api_login_challenge_token
        UNIQUE (token_hash),

    CONSTRAINT chk_master_admin_api_login_challenge_version
        CHECK (
            security_session_version >= 0
        ),

    CONSTRAINT chk_master_admin_api_login_challenge_expiry
        CHECK (
            expires_at > created_at
        ),

    CONSTRAINT chk_master_admin_api_login_challenge_password_time
        CHECK (
            password_verified_at <= created_at
            AND password_verified_at < expires_at
        ),

    CONSTRAINT chk_master_admin_api_login_challenge_consumed
        CHECK (
            consumed_at IS NULL
            OR consumed_at >= created_at
        ),

    CONSTRAINT chk_master_admin_api_login_challenge_revoked
        CHECK (
            revoked_at IS NULL
            OR revoked_at >= created_at
        ),

    CONSTRAINT chk_master_admin_api_login_challenge_terminal
        CHECK (
            NOT (
                consumed_at IS NOT NULL
                AND revoked_at IS NOT NULL
            )
        )

);


CREATE INDEX IF NOT EXISTS
    master_admin_api_login_challenges_user_idx
ON master_admin_api_login_challenges (
    master_admin_user_id,
    created_at DESC
);


CREATE INDEX IF NOT EXISTS
    master_admin_api_login_challenges_active_idx
ON master_admin_api_login_challenges (
    expires_at
)
WHERE
    consumed_at IS NULL
    AND revoked_at IS NULL;


CREATE TABLE IF NOT EXISTS master_admin_api_sessions (

    master_admin_api_session_id BIGSERIAL PRIMARY KEY,

    master_admin_user_id INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    token_hash CHAR(64) NOT NULL,

    security_session_version INTEGER NOT NULL,

    password_changed_at_marker VARCHAR(64),

    issued_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    last_activity_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    absolute_expires_at TIMESTAMPTZ NOT NULL,

    revoked_at TIMESTAMPTZ,

    revoked_reason VARCHAR(64),

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_master_admin_api_session_token
        UNIQUE (token_hash),

    CONSTRAINT chk_master_admin_api_session_version
        CHECK (
            security_session_version >= 0
        ),

    CONSTRAINT chk_master_admin_api_session_expiry
        CHECK (
            absolute_expires_at > issued_at
        ),

    CONSTRAINT chk_master_admin_api_session_activity
        CHECK (
            last_activity_at >= issued_at
        ),

    CONSTRAINT chk_master_admin_api_session_revoked
        CHECK (
            revoked_at IS NULL
            OR revoked_at >= issued_at
        ),

    CONSTRAINT chk_master_admin_api_session_revoke_reason
        CHECK (
            (
                revoked_at IS NULL
                AND revoked_reason IS NULL
            )
            OR (
                revoked_at IS NOT NULL
                AND revoked_reason IS NOT NULL
            )
        ),

    CONSTRAINT chk_master_admin_api_session_updated
        CHECK (
            updated_at >= created_at
        )

);


CREATE INDEX IF NOT EXISTS
    master_admin_api_sessions_user_active_idx
ON master_admin_api_sessions (
    master_admin_user_id,
    last_activity_at DESC
)
WHERE revoked_at IS NULL;


CREATE INDEX IF NOT EXISTS
    master_admin_api_sessions_expiry_idx
ON master_admin_api_sessions (
    absolute_expires_at
)
WHERE revoked_at IS NULL;


COMMENT ON TABLE master_admin_api_login_challenges IS
    'Short-lived one-time password-authenticated challenges '
    'used before Master Admin authenticator verification. '
    'Only SHA-256 hashes of raw challenge tokens are stored.';


COMMENT ON COLUMN
    master_admin_api_login_challenges.token_hash
IS
    'SHA-256 hexadecimal hash of the one-time native login '
    'challenge token. The raw token is never stored.';


COMMENT ON TABLE master_admin_api_sessions IS
    'Revocable authenticated sessions for the native Master '
    'Admin API. These sessions are independent of Flask browser '
    'sessions and browser tab-presence heartbeat enforcement.';


COMMENT ON COLUMN
    master_admin_api_sessions.token_hash
IS
    'SHA-256 hexadecimal hash of the native Bearer token. '
    'The raw Bearer token is returned once to the authenticated '
    'client and is never stored in PostgreSQL.';


COMMENT ON COLUMN
    master_admin_api_sessions.security_session_version
IS
    'Snapshot of users.security_session_version when the native '
    'session was issued. A mismatch invalidates the session.';


COMMENT ON COLUMN
    master_admin_api_sessions.password_changed_at_marker
IS
    'ISO-format snapshot of users.password_changed_at when the '
    'native session was issued. A mismatch invalidates the session.';


COMMENT ON COLUMN
    master_admin_api_sessions.revoked_reason
IS
    'Sanitized server-defined reason for session revocation. '
    'Do not store credentials, tokens, or other secrets here.';


COMMIT;
