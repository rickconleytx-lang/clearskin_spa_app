BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- BUSINESS USER INVITATIONS V1
--
-- Secure one-time invitations for people who do not yet
-- have a PSP user account for the newly provisioned business.
--
-- Invitations preserve business relationship separately
-- from PSP workspace permissions.
--
-- Raw invitation tokens are NEVER stored.
-- Application code stores only a SHA-256 token hash.
-- =========================================================


CREATE TABLE IF NOT EXISTS business_user_invitations (

    business_user_invitation_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    business_unit_id INTEGER NOT NULL,

    employee_id INTEGER,

    invited_first_name VARCHAR(100) NOT NULL,

    invited_last_name VARCHAR(100) NOT NULL,

    invited_email VARCHAR(254) NOT NULL,

    business_relationship_code VARCHAR(40) NOT NULL,

    membership_role_code VARCHAR(40) NOT NULL,

    is_primary_onboarding_invitation BOOLEAN
        NOT NULL DEFAULT FALSE,

    token_hash CHAR(64) NOT NULL UNIQUE,

    invited_by_user_id INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    accepted_user_id INTEGER
        REFERENCES users(user_id)
        ON DELETE RESTRICT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    expires_at TIMESTAMPTZ NOT NULL,

    email_sent_at TIMESTAMPTZ,

    accepted_at TIMESTAMPTZ,

    invalidated_at TIMESTAMPTZ,

    CONSTRAINT business_user_invitations_workspace_fk
        FOREIGN KEY (
            spa_id,
            business_unit_id
        )
        REFERENCES business_units (
            spa_id,
            business_unit_id
        )
        ON DELETE CASCADE,

    CONSTRAINT business_user_invitations_employee_fk
        FOREIGN KEY (
            spa_id,
            employee_id
        )
        REFERENCES employees (
            spa_id,
            employee_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT business_user_invitations_relationship_check
        CHECK (
            business_relationship_code IN (
                'owner',
                'manager_administrator',
                'employee_provider',
                'it_technical_administrator',
                'other'
            )
        ),

    CONSTRAINT business_user_invitations_membership_role_check
        CHECK (
            membership_role_code IN (
                'organization_admin',
                'management',
                'staff',
                'provider',
                'front_desk'
            )
        ),

    CONSTRAINT business_user_invitations_owner_check
        CHECK (
            business_relationship_code <> 'owner'
            OR (
                employee_id IS NOT NULL
                AND membership_role_code = 'organization_admin'
            )
        ),

    CONSTRAINT business_user_invitations_primary_check
        CHECK (
            is_primary_onboarding_invitation = FALSE
            OR business_relationship_code = 'owner'
        ),

    CONSTRAINT business_user_invitations_expires_check
        CHECK (
            expires_at > created_at
        ),

    CONSTRAINT business_user_invitations_email_sent_check
        CHECK (
            email_sent_at IS NULL
            OR email_sent_at >= created_at
        ),

    CONSTRAINT business_user_invitations_accepted_check
        CHECK (
            (
                accepted_at IS NULL
                AND accepted_user_id IS NULL
            )
            OR (
                accepted_at IS NOT NULL
                AND accepted_user_id IS NOT NULL
                AND accepted_at >= created_at
                AND email_sent_at IS NOT NULL
            )
        ),

    CONSTRAINT business_user_invitations_invalidated_check
        CHECK (
            invalidated_at IS NULL
            OR invalidated_at >= created_at
        ),

    CONSTRAINT business_user_invitations_terminal_state_check
        CHECK (
            NOT (
                accepted_at IS NOT NULL
                AND invalidated_at IS NOT NULL
            )
        )
);


CREATE UNIQUE INDEX
    business_user_invitations_active_email_idx
ON business_user_invitations (
    spa_id,
    business_unit_id,
    LOWER(BTRIM(invited_email))
)
WHERE email_sent_at IS NOT NULL
  AND accepted_at IS NULL
  AND invalidated_at IS NULL;


CREATE UNIQUE INDEX
    business_user_invitations_primary_active_idx
ON business_user_invitations (
    spa_id
)
WHERE is_primary_onboarding_invitation = TRUE
  AND email_sent_at IS NOT NULL
  AND accepted_at IS NULL
  AND invalidated_at IS NULL;


CREATE INDEX
    business_user_invitations_active_expiry_idx
ON business_user_invitations (
    expires_at
)
WHERE accepted_at IS NULL
  AND invalidated_at IS NULL;


CREATE INDEX
    business_user_invitations_employee_idx
ON business_user_invitations (
    spa_id,
    employee_id
)
WHERE employee_id IS NOT NULL;


COMMENT ON TABLE business_user_invitations IS
    'Secure one-time invitations used to establish PSP user access. '
    'The invitation does not itself establish business ownership.';


COMMENT ON COLUMN
    business_user_invitations.business_relationship_code IS
    'Describes the invitee relationship to the business. This value '
    'does not itself grant PSP permissions.';


COMMENT ON COLUMN
    business_user_invitations.membership_role_code IS
    'PSP workspace permission role to create when the invitation is '
    'accepted. Business ownership remains authoritative through the '
    'employee Owner role, not this field.';


COMMENT ON COLUMN
    business_user_invitations.employee_id IS
    'Optional existing employee identity to link to the PSP workspace '
    'membership at invitation acceptance. Required for the Owner.';


COMMENT ON COLUMN
    business_user_invitations.is_primary_onboarding_invitation IS
    'TRUE only for the Owner invitation whose successful activation '
    'allows first-time business onboarding to continue.';


COMMENT ON COLUMN
    business_user_invitations.token_hash IS
    'SHA-256 hexadecimal hash of the raw invitation token. The raw '
    'token exists only in the invitation URL sent to the recipient.';


COMMENT ON COLUMN
    business_user_invitations.email_sent_at IS
    'Set only after the invitation email is accepted by the mail '
    'provider.';


COMMENT ON COLUMN
    business_user_invitations.accepted_at IS
    'Set when the invitation successfully establishes PSP user access.';


COMMENT ON COLUMN
    business_user_invitations.invalidated_at IS
    'Set when the invitation is revoked or superseded without being '
    'accepted.';


COMMIT;
