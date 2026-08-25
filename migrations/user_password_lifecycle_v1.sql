BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- USER PASSWORD LIFECYCLE V1
--
-- Adds password lifecycle state for Peach Suite Pro
-- business-login accounts.
--
-- Existing users are not forced to change their password
-- when this migration is deployed.
-- =========================================================


ALTER TABLE users
    ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ;


ALTER TABLE users
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN
        NOT NULL DEFAULT FALSE;


COMMENT ON COLUMN users.password_changed_at
IS
    'Timestamp of the most recent successful Peach Suite Pro '
    'business-login password change or reset.';


COMMENT ON COLUMN users.must_change_password
IS
    'When TRUE, the user must replace the current business-login '
    'password before continuing normal Peach Suite Pro use. '
    'Existing users default to FALSE.';


COMMIT;
