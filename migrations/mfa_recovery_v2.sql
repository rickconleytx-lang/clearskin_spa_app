-- Peach Suite Pro
-- MFA Account Recovery V2
--
-- Adds pre-established trusted recovery contacts, a high-entropy
-- Account Recovery Key, persistent account-recovery requests, and
-- recorded recovery proofs.
--
-- Security model:
-- - Normal MFA remains one active login-verification method.
-- - Existing one-time Authenticator recovery codes remain unchanged.
-- - Catastrophic self-service recovery requires 2 different proofs
--   from Trusted Recovery Email, Trusted Recovery Phone, and the
--   PSP Account Recovery Key.
-- - Recovery contacts must be established and verified before they
--   may be used for account recovery.
-- - Raw verification codes and raw Account Recovery Keys are never
--   stored.
-- - Assisted Recovery is tracked separately and must not silently
--   bypass the normal MFA login path.


BEGIN;


-- Every normal business session stores this version when login
-- completes. Security-sensitive account recovery increments it,
-- invalidating all previously established business sessions without
-- pretending that the user's password changed.
ALTER TABLE users
    ADD COLUMN security_session_version BIGINT NOT NULL DEFAULT 1;


ALTER TABLE users
    ADD CONSTRAINT users_security_session_version_check
        CHECK (security_session_version >= 1);


COMMENT ON COLUMN users.security_session_version IS
    'Account-level business-session security version. Incrementing this '
    'value invalidates previously established normal business sessions.';


CREATE TABLE mfa_recovery_contacts (

    mfa_recovery_contact_id SERIAL PRIMARY KEY,

    user_id INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    contact_type VARCHAR(20) NOT NULL,

    contact_value TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    verified_at TIMESTAMPTZ,

    revoked_at TIMESTAMPTZ,

    last_used_at TIMESTAMPTZ,

    CONSTRAINT mfa_recovery_contacts_type_check
        CHECK (
            contact_type IN (
                'email',
                'sms'
            )
        ),

    CONSTRAINT mfa_recovery_contacts_value_check
        CHECK (
            LENGTH(BTRIM(contact_value)) > 0
        ),

    CONSTRAINT mfa_recovery_contacts_verified_check
        CHECK (
            verified_at IS NULL
            OR verified_at >= created_at
        ),

    CONSTRAINT mfa_recovery_contacts_revoked_check
        CHECK (
            revoked_at IS NULL
            OR revoked_at >= created_at
        ),

    CONSTRAINT mfa_recovery_contacts_last_used_check
        CHECK (
            last_used_at IS NULL
            OR (
                verified_at IS NOT NULL
                AND last_used_at >= verified_at
            )
        )
);


-- One verified current recovery destination of each type.
ALTER TABLE mfa_recovery_contacts
    ADD CONSTRAINT mfa_recovery_contacts_id_user_type_unique
        UNIQUE (
            mfa_recovery_contact_id,
            user_id,
            contact_type
        );


CREATE UNIQUE INDEX mfa_recovery_contacts_current_verified_idx
    ON mfa_recovery_contacts (
        user_id,
        contact_type
    )
    WHERE verified_at IS NOT NULL
      AND revoked_at IS NULL;


-- Allow one replacement contact to be pending verification while the
-- currently trusted contact remains active.
CREATE UNIQUE INDEX mfa_recovery_contacts_current_pending_idx
    ON mfa_recovery_contacts (
        user_id,
        contact_type
    )
    WHERE verified_at IS NULL
      AND revoked_at IS NULL;


CREATE INDEX mfa_recovery_contacts_user_history_idx
    ON mfa_recovery_contacts (
        user_id,
        contact_type,
        created_at DESC
    );


COMMENT ON TABLE mfa_recovery_contacts IS
    'Pre-established Peach Suite Pro trusted account-recovery email '
    'and phone destinations. A contact is not trusted until verified.';


COMMENT ON COLUMN mfa_recovery_contacts.contact_value IS
    'Normalized destination used for recovery verification. Recovery '
    'contacts are distinct from the normal login email or MFA phone.';


COMMENT ON COLUMN mfa_recovery_contacts.verified_at IS
    'Set only after a verification challenge sent to this exact '
    'recovery destination succeeds.';


COMMENT ON COLUMN mfa_recovery_contacts.revoked_at IS
    'Set when a trusted or pending recovery contact is replaced, '
    'removed, or revoked. Historical rows remain for audit context.';


-- Extend the existing short-lived SMS/email challenge engine so
-- recovery verification retains the same hashing, expiry, delivery,
-- invalidation, and one-time-consumption protections.
ALTER TABLE mfa_verification_challenges
    ADD COLUMN recovery_contact_id INTEGER;


ALTER TABLE mfa_verification_challenges
    ADD CONSTRAINT mfa_verification_challenges_recovery_contact_owner_fk
        FOREIGN KEY (
            recovery_contact_id,
            user_id,
            method
        )
        REFERENCES mfa_recovery_contacts (
            mfa_recovery_contact_id,
            user_id,
            contact_type
        )
        ON DELETE RESTRICT;


ALTER TABLE mfa_verification_challenges
    DROP CONSTRAINT mfa_verification_challenges_purpose_check;


ALTER TABLE mfa_verification_challenges
    ADD CONSTRAINT mfa_verification_challenges_purpose_check
        CHECK (
            purpose IN (
                'enrollment',
                'login',
                'method_change',
                'recovery_contact_setup',
                'account_recovery',
                'account_recovery_rebuild'
            )
        );


-- Recovery-context constraints are added after the persistent
-- account-recovery request table is created.


CREATE INDEX mfa_verification_challenges_recovery_contact_idx
    ON mfa_verification_challenges (
        recovery_contact_id,
        created_at DESC
    )
    WHERE recovery_contact_id IS NOT NULL;


COMMENT ON COLUMN mfa_verification_challenges.recovery_contact_id IS

    'Exact trusted or pending recovery contact targeted by recovery '

    'proof or setup. NULL for ordinary MFA and Account Recovery rebuild '

    'challenges.';


CREATE TABLE mfa_account_recovery_keys (

    mfa_account_recovery_key_id SERIAL PRIMARY KEY,

    user_id INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    key_hash CHAR(64) NOT NULL UNIQUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    last_used_at TIMESTAMPTZ,

    invalidated_at TIMESTAMPTZ,

    CONSTRAINT mfa_account_recovery_keys_last_used_check
        CHECK (
            last_used_at IS NULL
            OR last_used_at >= created_at
        ),

    CONSTRAINT mfa_account_recovery_keys_invalidated_check
        CHECK (
            invalidated_at IS NULL
            OR invalidated_at >= created_at
        )
);


ALTER TABLE mfa_account_recovery_keys
    ADD CONSTRAINT mfa_account_recovery_keys_id_user_unique
        UNIQUE (
            mfa_account_recovery_key_id,
            user_id
        );


-- A user may have historical invalidated keys but only one active
-- Account Recovery Key at a time.
CREATE UNIQUE INDEX mfa_account_recovery_keys_current_user_idx
    ON mfa_account_recovery_keys (
        user_id
    )
    WHERE invalidated_at IS NULL;


CREATE INDEX mfa_account_recovery_keys_user_history_idx
    ON mfa_account_recovery_keys (
        user_id,
        created_at DESC
    );


COMMENT ON TABLE mfa_account_recovery_keys IS
    'High-entropy Peach Suite Pro Account Recovery Keys. Only keyed '
    'HMAC-SHA256 hashes are stored; the raw key is displayed once.';


COMMENT ON COLUMN mfa_account_recovery_keys.key_hash IS
    'Domain-separated HMAC-SHA256 hash of the 128-bit Account Recovery '
    'Key using the server-side MFA recovery pepper.';


COMMENT ON COLUMN mfa_account_recovery_keys.invalidated_at IS
    'Set when the key is replaced, revoked, or rotated after successful '
    'account recovery.';


CREATE TABLE mfa_account_recovery_requests (

    mfa_account_recovery_request_id SERIAL PRIMARY KEY,

    user_id INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    status VARCHAR(30) NOT NULL DEFAULT 'pending',

    required_proof_count SMALLINT NOT NULL DEFAULT 2,

    password_verified_at TIMESTAMPTZ NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    expires_at TIMESTAMPTZ NOT NULL,

    recovery_verified_at TIMESTAMPTZ,

    restricted_session_started_at TIMESTAMPTZ,

    security_hold_until TIMESTAMPTZ,

    assisted_requested_at TIMESTAMPTZ,

    assisted_approved_at TIMESTAMPTZ,

    assisted_approved_by_user_id INTEGER
        REFERENCES users(user_id)
        ON DELETE RESTRICT,

    compromised_factor_reported BOOLEAN NOT NULL DEFAULT FALSE,

    completed_at TIMESTAMPTZ,

    cancelled_at TIMESTAMPTZ,

    CONSTRAINT mfa_account_recovery_requests_status_check
        CHECK (
            status IN (
                'pending',
                'self_service_verified',
                'restricted',
                'assisted_review',
                'assisted_approved',
                'completed',
                'cancelled',
                'expired'
            )
        ),

    CONSTRAINT mfa_account_recovery_requests_proof_count_check
        CHECK (
            required_proof_count BETWEEN 2 AND 3
        ),

    CONSTRAINT mfa_account_recovery_requests_expiry_check
        CHECK (
            expires_at > created_at
        ),

    CONSTRAINT mfa_account_recovery_requests_password_check
        CHECK (
            password_verified_at
                >= created_at - INTERVAL '15 minutes'
            AND password_verified_at
                <= created_at + INTERVAL '1 minute'
        ),

    CONSTRAINT mfa_account_recovery_requests_verified_check
        CHECK (
            recovery_verified_at IS NULL
            OR recovery_verified_at >= created_at
        ),

    CONSTRAINT mfa_account_recovery_requests_restricted_check
        CHECK (
            restricted_session_started_at IS NULL
            OR (
                recovery_verified_at IS NOT NULL
                AND restricted_session_started_at >= recovery_verified_at
            )
        ),

    CONSTRAINT mfa_account_recovery_requests_hold_check
        CHECK (
            security_hold_until IS NULL
            OR security_hold_until >= created_at
        ),

    CONSTRAINT mfa_account_recovery_requests_assisted_request_check
        CHECK (
            assisted_requested_at IS NULL
            OR assisted_requested_at >= created_at
        ),

    CONSTRAINT mfa_account_recovery_requests_assisted_approval_check
        CHECK (
            assisted_approved_at IS NULL
            OR (
                assisted_requested_at IS NOT NULL
                AND assisted_approved_at >= assisted_requested_at
            )
        ),

    CONSTRAINT mfa_account_recovery_requests_assisted_approver_check
        CHECK (
            (
                assisted_approved_at IS NULL
                AND assisted_approved_by_user_id IS NULL
            )
            OR
            (
                assisted_approved_at IS NOT NULL
                AND assisted_approved_by_user_id IS NOT NULL
            )
        ),

    CONSTRAINT mfa_account_recovery_requests_completed_check
        CHECK (
            completed_at IS NULL
            OR completed_at >= created_at
        ),

    CONSTRAINT mfa_account_recovery_requests_cancelled_check
        CHECK (
            cancelled_at IS NULL
            OR cancelled_at >= created_at
        )
);


ALTER TABLE mfa_account_recovery_requests
    ADD CONSTRAINT mfa_account_recovery_requests_id_user_unique
        UNIQUE (
            mfa_account_recovery_request_id,
            user_id
        );


-- Do not allow parallel active recovery cases for the same account.
CREATE UNIQUE INDEX mfa_account_recovery_requests_active_user_idx
    ON mfa_account_recovery_requests (
        user_id
    )
    WHERE status NOT IN (
        'completed',
        'cancelled',
        'expired'
    );


CREATE INDEX mfa_account_recovery_requests_user_history_idx
    ON mfa_account_recovery_requests (
        user_id,
        created_at DESC
    );


CREATE INDEX mfa_account_recovery_requests_assisted_review_idx
    ON mfa_account_recovery_requests (
        created_at
    )
    WHERE status = 'assisted_review';


COMMENT ON TABLE mfa_account_recovery_requests IS
    'Persistent Peach Suite Pro catastrophic account-recovery cases. '
    'Successful proof does not itself create a normal business session.';


COMMENT ON COLUMN mfa_account_recovery_requests.required_proof_count IS
    'Number of different self-service recovery factors required. '
    'Normally 2 of the three available recovery factor types.';


COMMENT ON COLUMN mfa_account_recovery_requests.password_verified_at IS
    'Records that the normal account password was successfully verified '
    'before this recovery request was created.';


COMMENT ON COLUMN mfa_account_recovery_requests.restricted_session_started_at IS
    'Set when recovery verification has opened the narrowly scoped '
    'Recovery Session used to rebuild MFA before normal login.';


ALTER TABLE mfa_verification_challenges
    ADD COLUMN recovery_request_id INTEGER;


ALTER TABLE mfa_verification_challenges
    ADD CONSTRAINT mfa_verification_challenges_recovery_request_owner_fk
        FOREIGN KEY (
            recovery_request_id,
            user_id
        )
        REFERENCES mfa_account_recovery_requests (
            mfa_account_recovery_request_id,
            user_id
        )
        ON DELETE RESTRICT;


ALTER TABLE mfa_verification_challenges
    ADD CONSTRAINT mfa_verification_challenges_id_user_unique
        UNIQUE (
            mfa_verification_challenge_id,
            user_id
        );


ALTER TABLE mfa_verification_challenges
    ADD CONSTRAINT mfa_verification_challenges_recovery_proof_unique
        UNIQUE (
            mfa_verification_challenge_id,
            user_id,
            recovery_request_id,
            recovery_contact_id,
            method
        );


-- Ordinary MFA challenges cannot target recovery records.
-- Recovery-contact setup targets only the exact pending contact.
-- Catastrophic account recovery targets both the exact trusted
-- contact and the exact persistent recovery request.
ALTER TABLE mfa_verification_challenges
    ADD CONSTRAINT mfa_verification_challenges_recovery_context_check
        CHECK (
            (
                purpose IN (
                    'enrollment',
                    'login',
                    'method_change'
                )
                AND recovery_contact_id IS NULL
                AND recovery_request_id IS NULL
            )
            OR
            (
                purpose = 'recovery_contact_setup'
                AND recovery_contact_id IS NOT NULL
                AND recovery_request_id IS NULL
            )
            OR
            (
                purpose = 'account_recovery'
                AND recovery_contact_id IS NOT NULL
                AND recovery_request_id IS NOT NULL
            )
            OR
            (
                purpose = 'account_recovery_rebuild'
                AND recovery_contact_id IS NULL
                AND recovery_request_id IS NOT NULL
            )
        );


CREATE INDEX mfa_verification_challenges_recovery_request_idx
    ON mfa_verification_challenges (
        recovery_request_id,
        created_at DESC
    )
    WHERE recovery_request_id IS NOT NULL;


COMMENT ON COLUMN mfa_verification_challenges.recovery_request_id IS

    'Exact persistent catastrophic-recovery request associated with an '

    'account_recovery proof or account_recovery_rebuild challenge. NULL '

    'for all other MFA purposes.';


-- One restricted MFA rebuild engine supports every PSP MFA method.
--
-- Authenticator:
--   replacement_authenticator_id identifies the exact fresh enrollment.
--
-- Text / Email:
--   replacement_verification_challenge_id identifies the exact fresh
--   SMS/email challenge.
--
-- Persisting the exact replacement credential prevents interrupted
-- Account Recovery from guessing which MFA credential belongs to the
-- recovery case.


ALTER TABLE mfa_authenticators

    ADD CONSTRAINT mfa_authenticators_id_user_unique
        UNIQUE (
            mfa_authenticator_id,
            user_id
        );


ALTER TABLE mfa_verification_challenges

    ADD CONSTRAINT mfa_verification_challenges_id_user_request_method_unique
        UNIQUE (
            mfa_verification_challenge_id,
            user_id,
            recovery_request_id,
            method
        );


ALTER TABLE mfa_account_recovery_requests

    ADD COLUMN mfa_rebuild_method VARCHAR(20),

    ADD COLUMN mfa_rebuild_started_at TIMESTAMPTZ,

    ADD COLUMN replacement_authenticator_id INTEGER,

    ADD COLUMN replacement_verification_challenge_id INTEGER,

    ADD COLUMN mfa_rebuild_verified_at TIMESTAMPTZ;


ALTER TABLE mfa_account_recovery_requests

    ADD CONSTRAINT mfa_account_recovery_requests_rebuild_method_check
        CHECK (
            mfa_rebuild_method IS NULL
            OR mfa_rebuild_method IN (
                'authenticator',
                'sms',
                'email'
            )
        ),

    ADD CONSTRAINT mfa_account_recovery_requests_rebuild_state_check
        CHECK (
            (
                mfa_rebuild_method IS NULL
                AND mfa_rebuild_started_at IS NULL
                AND replacement_authenticator_id IS NULL
                AND replacement_verification_challenge_id IS NULL
                AND mfa_rebuild_verified_at IS NULL
            )
            OR
            (
                mfa_rebuild_method = 'authenticator'
                AND mfa_rebuild_started_at IS NOT NULL
                AND replacement_authenticator_id IS NOT NULL
                AND replacement_verification_challenge_id IS NULL
            )
            OR
            (
                mfa_rebuild_method IN (
                    'sms',
                    'email'
                )
                AND mfa_rebuild_started_at IS NOT NULL
                AND replacement_authenticator_id IS NULL
                AND replacement_verification_challenge_id IS NOT NULL
            )
        ),

    ADD CONSTRAINT mfa_account_recovery_requests_rebuild_started_check
        CHECK (
            mfa_rebuild_started_at IS NULL
            OR (
                restricted_session_started_at IS NOT NULL
                AND mfa_rebuild_started_at
                    >= restricted_session_started_at
            )
        ),

    ADD CONSTRAINT mfa_account_recovery_requests_rebuild_verified_check
        CHECK (
            mfa_rebuild_verified_at IS NULL
            OR (
                mfa_rebuild_started_at IS NOT NULL
                AND mfa_rebuild_verified_at
                    >= mfa_rebuild_started_at
            )
        ),

    ADD CONSTRAINT mfa_account_recovery_requests_replacement_authenticator_fk
        FOREIGN KEY (
            replacement_authenticator_id,
            user_id
        )
        REFERENCES mfa_authenticators (
            mfa_authenticator_id,
            user_id
        )
        ON DELETE RESTRICT,

    ADD CONSTRAINT mfa_account_recovery_requests_replacement_challenge_fk
        FOREIGN KEY (
            replacement_verification_challenge_id,
            user_id,
            mfa_account_recovery_request_id,
            mfa_rebuild_method
        )
        REFERENCES mfa_verification_challenges (
            mfa_verification_challenge_id,
            user_id,
            recovery_request_id,
            method
        )
        ON DELETE RESTRICT;


COMMENT ON COLUMN mfa_account_recovery_requests.mfa_rebuild_method IS

    'Fresh MFA method being established inside restricted Account '

    'Recovery: authenticator, sms, or email.';


COMMENT ON COLUMN mfa_account_recovery_requests.mfa_rebuild_started_at IS

    'Set when restricted Account Recovery begins replacing the prior '

    'MFA credential.';


COMMENT ON COLUMN mfa_account_recovery_requests.replacement_authenticator_id IS

    'Exact fresh Authenticator enrollment created by this recovery case. '

    'NULL for Text or Email rebuilds.';


COMMENT ON COLUMN mfa_account_recovery_requests.replacement_verification_challenge_id IS

    'Exact fresh SMS/email MFA challenge created by this recovery case '

    'and database-bound to the same request and rebuild method.';


COMMENT ON COLUMN mfa_account_recovery_requests.mfa_rebuild_verified_at IS

    'Set after the fresh replacement MFA credential is successfully '

    'verified. This alone does not create a normal business session.';


-- A restricted recovery may outlive its short browser session.
-- A fresh password-authenticated restart must prove the required
-- recovery factors again before the same restricted request resumes.
-- Prior proofs remain stored for audit but are superseded below.


ALTER TABLE mfa_account_recovery_requests

    ADD COLUMN proof_reverification_started_at TIMESTAMPTZ,

    ADD COLUMN proof_reverification_expires_at TIMESTAMPTZ,

    ADD COLUMN proof_reverification_verified_at TIMESTAMPTZ;


ALTER TABLE mfa_account_recovery_requests

    ADD CONSTRAINT mfa_account_recovery_requests_proof_reverification_check
        CHECK (
            (
                proof_reverification_started_at IS NULL
                AND proof_reverification_expires_at IS NULL
                AND proof_reverification_verified_at IS NULL
            )
            OR
            (
                proof_reverification_started_at IS NOT NULL
                AND proof_reverification_expires_at IS NOT NULL
                AND proof_reverification_expires_at
                    > proof_reverification_started_at
                AND (
                    proof_reverification_verified_at IS NULL
                    OR (
                        proof_reverification_verified_at
                            >= proof_reverification_started_at
                        AND proof_reverification_verified_at
                            <= proof_reverification_expires_at
                    )
                )
            )
        ),

    ADD CONSTRAINT mfa_account_recovery_requests_proof_reverification_started_check
        CHECK (
            proof_reverification_started_at IS NULL
            OR (
                restricted_session_started_at IS NOT NULL
                AND proof_reverification_started_at
                    >= restricted_session_started_at
            )
        );


COMMENT ON COLUMN mfa_account_recovery_requests.proof_reverification_started_at IS

    'Start of the current fresh-proof window used to resume an '

    'interrupted restricted Account Recovery request.';


COMMENT ON COLUMN mfa_account_recovery_requests.proof_reverification_expires_at IS

    'Expiration of the current fresh recovery-proof window for an '

    'interrupted restricted Account Recovery request.';


COMMENT ON COLUMN mfa_account_recovery_requests.proof_reverification_verified_at IS

    'Set after the required fresh recovery factors are re-proven for '

    'the current interrupted-recovery resume attempt.';


CREATE TABLE mfa_account_recovery_proofs (

    mfa_account_recovery_proof_id SERIAL PRIMARY KEY,

    mfa_account_recovery_request_id INTEGER NOT NULL
        REFERENCES mfa_account_recovery_requests(
            mfa_account_recovery_request_id
        )
        ON DELETE CASCADE,

    user_id INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    proof_type VARCHAR(30) NOT NULL,

    recovery_contact_id INTEGER
        REFERENCES mfa_recovery_contacts(mfa_recovery_contact_id),

    recovery_method VARCHAR(20),

    recovery_key_id INTEGER
        REFERENCES mfa_account_recovery_keys(
            mfa_account_recovery_key_id
        ),

    verification_challenge_id INTEGER
        REFERENCES mfa_verification_challenges(
            mfa_verification_challenge_id
        ),

    verified_by_user_id INTEGER
        REFERENCES users(user_id)
        ON DELETE RESTRICT,

    superseded_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT mfa_account_recovery_proofs_request_owner_fk
        FOREIGN KEY (
            mfa_account_recovery_request_id,
            user_id
        )
        REFERENCES mfa_account_recovery_requests (
            mfa_account_recovery_request_id,
            user_id
        )
        ON DELETE CASCADE,

    CONSTRAINT mfa_account_recovery_proofs_contact_owner_fk
        FOREIGN KEY (
            recovery_contact_id,
            user_id,
            recovery_method
        )
        REFERENCES mfa_recovery_contacts (
            mfa_recovery_contact_id,
            user_id,
            contact_type
        )
        ON DELETE RESTRICT,

    CONSTRAINT mfa_account_recovery_proofs_key_owner_fk
        FOREIGN KEY (
            recovery_key_id,
            user_id
        )
        REFERENCES mfa_account_recovery_keys (
            mfa_account_recovery_key_id,
            user_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT mfa_account_recovery_proofs_challenge_owner_fk
        FOREIGN KEY (
            verification_challenge_id,
            user_id,
            mfa_account_recovery_request_id,
            recovery_contact_id,
            recovery_method
        )
        REFERENCES mfa_verification_challenges (
            mfa_verification_challenge_id,
            user_id,
            recovery_request_id,
            recovery_contact_id,
            method
        )
        ON DELETE RESTRICT,

    CONSTRAINT mfa_account_recovery_proofs_type_check
        CHECK (
            proof_type IN (
                'recovery_email',
                'recovery_sms',
                'recovery_key',
                'assisted_recovery'
            )
        ),

    CONSTRAINT mfa_account_recovery_proofs_context_check
        CHECK (
            (
                proof_type = 'recovery_email'
                AND recovery_contact_id IS NOT NULL
                AND recovery_method = 'email'
                AND recovery_key_id IS NULL
                AND verification_challenge_id IS NOT NULL
                AND verified_by_user_id IS NULL
            )
            OR
            (
                proof_type = 'recovery_sms'
                AND recovery_contact_id IS NOT NULL
                AND recovery_method = 'sms'
                AND recovery_key_id IS NULL
                AND verification_challenge_id IS NOT NULL
                AND verified_by_user_id IS NULL
            )
            OR
            (
                proof_type = 'recovery_key'
                AND recovery_contact_id IS NULL
                AND recovery_method IS NULL
                AND recovery_key_id IS NOT NULL
                AND verification_challenge_id IS NULL
                AND verified_by_user_id IS NULL
            )
            OR
            (
                proof_type = 'assisted_recovery'
                AND recovery_contact_id IS NULL
                AND recovery_method IS NULL
                AND recovery_key_id IS NULL
                AND verification_challenge_id IS NULL
                AND verified_by_user_id IS NOT NULL
            )
        ),

    CONSTRAINT mfa_account_recovery_proofs_verified_check
        CHECK (
            verified_at >= created_at
        ),

    CONSTRAINT mfa_account_recovery_proofs_superseded_check
        CHECK (
            superseded_at IS NULL
            OR superseded_at >= verified_at
        )
);


CREATE UNIQUE INDEX mfa_account_recovery_proofs_active_type_unique
    ON mfa_account_recovery_proofs (
        mfa_account_recovery_request_id,
        proof_type
    )
    WHERE superseded_at IS NULL;


CREATE INDEX mfa_account_recovery_proofs_request_idx
    ON mfa_account_recovery_proofs (
        mfa_account_recovery_request_id,
        verified_at
    );


COMMENT ON TABLE mfa_account_recovery_proofs IS
    'Verified proofs associated with one account-recovery request. '
    'Only one current proof of each type may count toward recovery. '
    'Superseded proofs remain stored for security audit history.';


COMMENT ON COLUMN mfa_account_recovery_proofs.proof_type IS
    'Independent recovery factor: trusted recovery email, trusted '
    'recovery phone, Account Recovery Key, or audited Assisted Recovery.';


COMMIT;
