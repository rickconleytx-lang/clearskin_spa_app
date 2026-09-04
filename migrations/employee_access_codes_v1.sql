BEGIN;

-- ============================================================
-- PEACH SUITE PRO
-- EMPLOYEE ACCESS CODES V1
--
-- Shared-workstation individual verification foundation.
--
-- Business login:
--   identifies the signed-in PSP user / tenant session.
--
-- Employee Access Code:
--   identifies the actual employee authorizing a sensitive
--   page or action within the current Provider Workspace.
--
-- IMPORTANT:
--   employees.verification_code_hash is intentionally NOT used
--   or modified. It is spa-wide legacy/dormant storage and is
--   not Enterprise-safe.
-- ============================================================


-- ============================================================
-- 1. COMPOSITE TENANT KEYS
--
-- employee_id and business_unit_id are already global primary
-- keys. These additional unique indexes allow strong composite
-- foreign keys that also enforce spa ownership.
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS
uq_employees_spa_employee
ON employees (
    spa_id,
    employee_id
);


CREATE UNIQUE INDEX IF NOT EXISTS
uq_business_units_spa_business_unit
ON business_units (
    spa_id,
    business_unit_id
);


-- ============================================================
-- 2. EMPLOYEE <-> BUSINESS UNIT MEMBERSHIP
--
-- One durable row per employee/workspace relationship.
-- Archive/revoke changes is_active instead of deleting history.
-- ============================================================

CREATE TABLE IF NOT EXISTS employee_business_unit_memberships (
    employee_business_unit_membership_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    assigned_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    assigned_by INTEGER,

    revoked_at TIMESTAMP WITHOUT TIME ZONE,
    revoked_by INTEGER,

    CONSTRAINT uq_employee_business_unit_membership
        UNIQUE (
            spa_id,
            business_unit_id,
            employee_id
        ),

    CONSTRAINT fk_employee_bu_membership_employee
        FOREIGN KEY (
            spa_id,
            employee_id
        )
        REFERENCES employees (
            spa_id,
            employee_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_employee_bu_membership_business_unit
        FOREIGN KEY (
            spa_id,
            business_unit_id
        )
        REFERENCES business_units (
            spa_id,
            business_unit_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_employee_bu_membership_assigned_by
        FOREIGN KEY (assigned_by)
        REFERENCES users(user_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_employee_bu_membership_revoked_by
        FOREIGN KEY (revoked_by)
        REFERENCES users(user_id)
        ON DELETE RESTRICT
);


CREATE INDEX IF NOT EXISTS
idx_employee_bu_memberships_workspace_active
ON employee_business_unit_memberships (
    spa_id,
    business_unit_id,
    is_active,
    employee_id
);


CREATE INDEX IF NOT EXISTS
idx_employee_bu_memberships_employee
ON employee_business_unit_memberships (
    spa_id,
    employee_id,
    is_active
);


-- ============================================================
-- 3. BACKFILL EMPLOYEE WORKSPACE MEMBERSHIP
--
-- Backfill ONLY where existing PSP data provides explicit
-- workspace evidence. Do not guess from spa_id alone.
--
-- Evidence:
--   appointments
--   income
--   provider booking hours
--   provider service assignments
--   provider time off
--   business-unit ownership
-- ============================================================

WITH employee_workspace_evidence AS (

    SELECT
        a.spa_id,
        a.business_unit_id,
        a.provider_employee_id AS employee_id
    FROM appointments a
    WHERE a.provider_employee_id IS NOT NULL
      AND a.business_unit_id IS NOT NULL

    UNION

    SELECT
        i.spa_id,
        i.business_unit_id,
        i.employee_id
    FROM income i
    WHERE i.employee_id IS NOT NULL
      AND i.business_unit_id IS NOT NULL

    UNION

    SELECT
        pbh.spa_id,
        pbh.business_unit_id,
        pbh.provider_employee_id AS employee_id
    FROM provider_booking_hours pbh
    WHERE pbh.provider_employee_id IS NOT NULL
      AND pbh.business_unit_id IS NOT NULL

    UNION

    SELECT
        pst.spa_id,
        pst.business_unit_id,
        pst.provider_employee_id AS employee_id
    FROM provider_service_types pst
    WHERE pst.provider_employee_id IS NOT NULL
      AND pst.business_unit_id IS NOT NULL

    UNION

    SELECT
        pto.spa_id,
        pto.business_unit_id,
        pto.provider_employee_id AS employee_id
    FROM provider_time_off pto
    WHERE pto.provider_employee_id IS NOT NULL
      AND pto.business_unit_id IS NOT NULL

    UNION

    SELECT
        bu.spa_id,
        bu.business_unit_id,
        bu.owner_employee_id AS employee_id
    FROM business_units bu
    WHERE bu.owner_employee_id IS NOT NULL
)

INSERT INTO employee_business_unit_memberships (
    spa_id,
    business_unit_id,
    employee_id,
    is_active
)

SELECT DISTINCT
    evidence.spa_id,
    evidence.business_unit_id,
    evidence.employee_id,
    (
        e.is_active = TRUE
        AND bu.is_active = TRUE
    ) AS is_active

FROM employee_workspace_evidence evidence

JOIN employees e
  ON e.employee_id = evidence.employee_id
 AND e.spa_id = evidence.spa_id

JOIN business_units bu
  ON bu.business_unit_id = evidence.business_unit_id
 AND bu.spa_id = evidence.spa_id

ON CONFLICT (
    spa_id,
    business_unit_id,
    employee_id
)
DO NOTHING;


-- ============================================================
-- 4. WORKSPACE EMPLOYEE ACCESS CODE SETTINGS
--
-- Owner/business administrator selects:
--   4 or 5 characters
--   numeric or alphanumeric
--
-- Feature remains disabled until a complete format is selected
-- and explicitly enabled.
-- ============================================================

CREATE TABLE IF NOT EXISTS employee_access_code_settings (
    employee_access_code_setting_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,

    code_length SMALLINT,
    code_character_set VARCHAR(20),

    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_by INTEGER,

    updated_at TIMESTAMP WITHOUT TIME ZONE,
    updated_by INTEGER,

    CONSTRAINT uq_employee_access_code_settings_workspace
        UNIQUE (
            spa_id,
            business_unit_id
        ),

    CONSTRAINT chk_employee_access_code_length
        CHECK (
            code_length IS NULL
            OR code_length IN (4, 5)
        ),

    CONSTRAINT chk_employee_access_code_character_set
        CHECK (
            code_character_set IS NULL
            OR code_character_set IN (
                'numeric',
                'alphanumeric'
            )
        ),

    CONSTRAINT chk_employee_access_code_enabled_format
        CHECK (
            is_enabled = FALSE
            OR (
                code_length IN (4, 5)
                AND code_character_set IN (
                    'numeric',
                    'alphanumeric'
                )
            )
        ),

    CONSTRAINT fk_employee_access_settings_business_unit
        FOREIGN KEY (
            spa_id,
            business_unit_id
        )
        REFERENCES business_units (
            spa_id,
            business_unit_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_employee_access_settings_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_employee_access_settings_updated_by
        FOREIGN KEY (updated_by)
        REFERENCES users(user_id)
        ON DELETE RESTRICT
);


-- ============================================================
-- 5. EMPLOYEE ACCESS CODE CREDENTIALS
--
-- No plaintext code is stored.
--
-- code_hash will hold a dedicated peppered/domain-separated
-- HMAC-SHA256 hex digest generated by the application.
--
-- Old credentials are revoked rather than overwritten/deleted,
-- preserving reset history without retaining the plaintext code.
-- ============================================================

CREATE TABLE IF NOT EXISTS employee_access_code_credentials (
    employee_access_code_credential_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,

    code_hash VARCHAR(64) NOT NULL,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_by INTEGER,

    revoked_at TIMESTAMP WITHOUT TIME ZONE,
    revoked_by INTEGER,
    revocation_reason VARCHAR(80),

    last_used_at TIMESTAMP WITHOUT TIME ZONE,

    CONSTRAINT chk_employee_access_code_hash
        CHECK (
            code_hash ~ '^[0-9a-f]{64}$'
        ),

    CONSTRAINT fk_employee_access_credential_membership
        FOREIGN KEY (
            spa_id,
            business_unit_id,
            employee_id
        )
        REFERENCES employee_business_unit_memberships (
            spa_id,
            business_unit_id,
            employee_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_employee_access_credential_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_employee_access_credential_revoked_by
        FOREIGN KEY (revoked_by)
        REFERENCES users(user_id)
        ON DELETE RESTRICT
);


-- One current code per employee/workspace.
CREATE UNIQUE INDEX IF NOT EXISTS
uq_employee_access_active_employee
ON employee_access_code_credentials (
    spa_id,
    business_unit_id,
    employee_id
)
WHERE is_active = TRUE;


-- No two active employees in the same workspace may share
-- the same generated code.
CREATE UNIQUE INDEX IF NOT EXISTS
uq_employee_access_active_code
ON employee_access_code_credentials (
    spa_id,
    business_unit_id,
    code_hash
)
WHERE is_active = TRUE;


CREATE INDEX IF NOT EXISTS
idx_employee_access_credentials_lookup
ON employee_access_code_credentials (
    spa_id,
    business_unit_id,
    code_hash,
    is_active
);


-- ============================================================
-- 6. VERIFICATION ATTEMPTS / RATE-LIMIT FOUNDATION
--
-- Never store the submitted access code or its plaintext.
--
-- This supports durable workspace/login-user throttling while
-- the employee identity is still unknown.
-- Exact failure-window and lockout policy remains application
-- configuration rather than a database constraint.
-- ============================================================

CREATE TABLE IF NOT EXISTS employee_access_code_attempts (
    employee_access_code_attempt_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    user_id INTEGER,

    -- Privacy-safe HMAC of the normalized request source.
    -- The raw IP/source address is never stored.
    source_hash VARCHAR(64) NOT NULL,

    -- Fingerprint of a random browser security-session nonce.
    -- The raw nonce remains only in the signed Flask session.
    security_session_hash VARCHAR(64) NOT NULL,

    page_scope VARCHAR(160) NOT NULL,

    was_successful BOOLEAN NOT NULL DEFAULT FALSE,

    verified_employee_id INTEGER,

    -- Set only when this failure creates or records an active
    -- Employee Access Code lockout.
    locked_until TIMESTAMP WITHOUT TIME ZONE,

    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_employee_access_attempt_source_hash
        CHECK (
            source_hash ~ '^[0-9a-f]{64}$'
        ),

    CONSTRAINT chk_employee_access_attempt_session_hash
        CHECK (
            security_session_hash ~ '^[0-9a-f]{64}$'
        ),

    CONSTRAINT fk_employee_access_attempt_business_unit
        FOREIGN KEY (
            spa_id,
            business_unit_id
        )
        REFERENCES business_units (
            spa_id,
            business_unit_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_employee_access_attempt_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_employee_access_attempt_employee
        FOREIGN KEY (
            spa_id,
            verified_employee_id
        )
        REFERENCES employees (
            spa_id,
            employee_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT chk_employee_access_attempt_result
        CHECK (
            (
                was_successful = TRUE
                AND verified_employee_id IS NOT NULL
                AND locked_until IS NULL
            )
            OR
            (
                was_successful = FALSE
                AND verified_employee_id IS NULL
            )
        )
);


CREATE INDEX IF NOT EXISTS
idx_employee_access_attempts_session_rate_limit
ON employee_access_code_attempts (
    spa_id,
    business_unit_id,
    user_id,
    security_session_hash,
    created_at DESC
);


CREATE INDEX IF NOT EXISTS
idx_employee_access_attempts_source_rate_limit
ON employee_access_code_attempts (
    spa_id,
    business_unit_id,
    source_hash,
    created_at DESC
);


CREATE INDEX IF NOT EXISTS
idx_employee_access_attempts_active_lock
ON employee_access_code_attempts (
    spa_id,
    business_unit_id,
    locked_until DESC
)
WHERE locked_until IS NOT NULL;


CREATE INDEX IF NOT EXISTS
idx_employee_access_attempts_workspace
ON employee_access_code_attempts (
    spa_id,
    business_unit_id,
    created_at DESC
);


-- ============================================================
-- 7. AUDIT LOG INDIVIDUAL-ACTOR FOUNDATION
--
-- user_id:
--   signed-in PSP business-login identity
--
-- verified_employee_id:
--   employee who successfully supplied the page-bound
--   Employee Access Code
--
-- business_unit_id:
--   workspace in which the action occurred
--
-- These audit identifiers intentionally remain historical IDs;
-- no destructive FK behavior is added to audit_log.
-- ============================================================

ALTER TABLE audit_log
    ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


ALTER TABLE audit_log
    ADD COLUMN IF NOT EXISTS verified_employee_id INTEGER;


CREATE INDEX IF NOT EXISTS
idx_audit_log_workspace
ON audit_log (
    spa_id,
    business_unit_id,
    created_at DESC
);


CREATE INDEX IF NOT EXISTS
idx_audit_log_verified_employee
ON audit_log (
    spa_id,
    business_unit_id,
    verified_employee_id,
    created_at DESC
);


COMMIT;
