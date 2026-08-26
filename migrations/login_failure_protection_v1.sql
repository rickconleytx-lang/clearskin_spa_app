BEGIN;

-- =========================================================
-- PEACH SUITE PRO
-- LOGIN FAILURE PROTECTION V1
--
-- Adds server-side failed-login state for Peach Suite Pro
-- business-login accounts.
--
-- Policy implemented by application code:
--   5 failed attempts within 15 minutes
--   -> 15-minute temporary authentication lock
--
-- Attempts during an active lock do not extend the lock.
-- Successful authentication clears failure state.
-- =========================================================

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS failed_login_count INTEGER
        NOT NULL DEFAULT 0;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS failed_login_window_started_at
        TIMESTAMPTZ;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_failed_login_at
        TIMESTAMPTZ;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS login_locked_until
        TIMESTAMPTZ;

ALTER TABLE users
    DROP CONSTRAINT IF EXISTS users_failed_login_count_check;

ALTER TABLE users
    ADD CONSTRAINT users_failed_login_count_check
        CHECK (failed_login_count >= 0);

COMMENT ON COLUMN users.failed_login_count
IS
    'Number of failed business-login attempts in the current '
    'login-failure window. Cleared after successful authentication.';

COMMENT ON COLUMN users.failed_login_window_started_at
IS
    'Timestamp when the current failed-login counting window began.';

COMMENT ON COLUMN users.last_failed_login_at
IS
    'Timestamp of the most recent failed business-login password '
    'attempt for this account.';

COMMENT ON COLUMN users.login_locked_until
IS
    'When set to a future timestamp, new business-login '
    'authentication attempts are temporarily blocked.';

COMMIT;
