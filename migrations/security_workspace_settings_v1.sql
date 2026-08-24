BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- SECURITY WORKSPACE SETTINGS V1
--
-- Workspace-level business login security policy.
--
-- Missing rows use application defaults:
--   inactivity timeout: 60 minutes
--   absolute session lifetime: 10 hours
-- =========================================================


CREATE TABLE IF NOT EXISTS security_workspace_settings (

    security_workspace_setting_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    inactivity_timeout_minutes INTEGER
        NOT NULL DEFAULT 60,

    absolute_session_hours INTEGER
        NOT NULL DEFAULT 10,

    created_by INTEGER,
    updated_by INTEGER,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_security_workspace_inactivity_timeout
        CHECK (
            inactivity_timeout_minutes IN (
                30,
                45,
                60,
                90
            )
        ),

    CONSTRAINT chk_security_workspace_absolute_session
        CHECK (
            absolute_session_hours IN (
                4,
                6,
                8,
                10
            )
        ),

    CONSTRAINT fk_security_workspace_settings_workspace
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_security_workspace_settings_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_security_workspace_settings_updated_by
        FOREIGN KEY (updated_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT uq_security_workspace_settings_workspace
        UNIQUE (
            spa_id,
            business_unit_id
        )
);


COMMENT ON COLUMN
    security_workspace_settings.inactivity_timeout_minutes
IS
    'Maximum period without actual Peach Suite Pro user '
    'interaction before the authenticated business session '
    'expires. Allowed values: 30, 45, 60, or 90 minutes.';


COMMENT ON COLUMN
    security_workspace_settings.absolute_session_hours
IS
    'Maximum authenticated business session lifetime before '
    'reauthentication is required. Allowed values: '
    '4, 6, 8, or 10 hours.';


COMMIT;
