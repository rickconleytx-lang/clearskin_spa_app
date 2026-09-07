-- Peach Suite Pro
-- Authenticator Replacement Safety V1
--
-- Support safe Authenticator replacement by allowing:
--
--   1. one verified, non-revoked active Authenticator, and
--   2. one unverified, non-revoked replacement candidate
--
-- for the same user at the same time.
--
-- This permits the existing Authenticator to remain usable until
-- the replacement candidate has been freshly verified.
--
-- Historical revoked Authenticator rows remain preserved.


BEGIN;


-- Fail closed if the database already contains a state that
-- would violate either replacement-safety uniqueness rule.
DO $$
BEGIN

    IF EXISTS (
        SELECT user_id
        FROM mfa_authenticators
        WHERE verified_at IS NOT NULL
          AND revoked_at IS NULL
        GROUP BY user_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Cannot migrate MFA authenticators: more than one active verified Authenticator exists for a user.';
    END IF;

    IF EXISTS (
        SELECT user_id
        FROM mfa_authenticators
        WHERE verified_at IS NULL
          AND revoked_at IS NULL
        GROUP BY user_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Cannot migrate MFA authenticators: more than one pending Authenticator candidate exists for a user.';
    END IF;

END
$$;


-- V1 allowed only one non-revoked row total. That prevents a
-- verified credential and its unverified replacement candidate
-- from coexisting during safe replacement.
DROP INDEX IF EXISTS
    mfa_authenticators_current_user_idx;


-- At most one usable verified Authenticator per user.
CREATE UNIQUE INDEX
    mfa_authenticators_active_verified_user_idx
ON mfa_authenticators (
    user_id
)
WHERE verified_at IS NOT NULL
  AND revoked_at IS NULL;


-- At most one unfinished/replacement Authenticator candidate
-- per user.
CREATE UNIQUE INDEX
    mfa_authenticators_pending_user_idx
ON mfa_authenticators (
    user_id
)
WHERE verified_at IS NULL
  AND revoked_at IS NULL;


COMMENT ON INDEX
    mfa_authenticators_active_verified_user_idx
IS
    'Allows at most one verified non-revoked Authenticator credential per Peach Suite Pro user.';


COMMENT ON INDEX
    mfa_authenticators_pending_user_idx
IS
    'Allows at most one unverified non-revoked Authenticator enrollment or replacement candidate per Peach Suite Pro user.';


COMMIT;
