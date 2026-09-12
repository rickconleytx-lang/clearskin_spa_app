BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- MASTER ADMIN ACKNOWLEDGEMENTS V1
--
-- Per-Master-Admin review watermarks for event-style
-- monitoring cards in the native Master Admin app.
--
-- Acknowledgement never deletes, modifies, or resolves the
-- underlying source event. It records only the time through
-- which the Master Admin has reviewed that monitoring scope.
--
-- Supported acknowledgement scopes:
--   security
--   alerts
--   recent_activity
--
-- System Health is intentionally excluded because active
-- health problems must remain yellow/red until resolved.
-- =========================================================


CREATE TABLE IF NOT EXISTS master_admin_acknowledgements (

    master_admin_acknowledgement_id BIGSERIAL PRIMARY KEY,

    user_id INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    acknowledgement_scope VARCHAR(32) NOT NULL,

    acknowledged_at TIMESTAMPTZ NOT NULL,

    created_by INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    updated_by INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_master_admin_acknowledgement_scope
        UNIQUE (
            user_id,
            acknowledgement_scope
        ),

    CONSTRAINT chk_master_admin_acknowledgement_scope
        CHECK (
            acknowledgement_scope IN (
                'security',
                'alerts',
                'recent_activity'
            )
        ),

    CONSTRAINT chk_master_admin_acknowledgement_updated
        CHECK (
            updated_at >= created_at
        )
);


COMMENT ON TABLE master_admin_acknowledgements IS
    'Per-user review timestamps for Peach Suite Pro Master Admin '
    'Security, Alerts, and Recent Activity monitoring cards.';


COMMENT ON COLUMN
    master_admin_acknowledgements.acknowledgement_scope
IS
    'Dashboard monitoring scope acknowledged by the Master Admin: '
    'security, alerts, or recent_activity.';


COMMENT ON COLUMN
    master_admin_acknowledgements.acknowledged_at
IS
    'Time through which the Master Admin has reviewed this monitoring '
    'scope. Events or relevant state changes after this time are new.';


COMMIT;
