BEGIN;


-- ==========================================================
-- PEACH SUITE PRO
-- MASTER ADMIN MONITORING STATUS V2
--
-- Generalize the persisted monitoring-status registry beyond
-- PeachWeb / PeachBook so provider health checks can share the
-- same current-state and transition-history architecture.
--
-- Additive migration.
-- ==========================================================


ALTER TABLE master_admin_monitoring_status
    DROP CONSTRAINT IF EXISTS
        chk_master_admin_monitoring_status_key;


ALTER TABLE master_admin_monitoring_status
    ADD CONSTRAINT
        chk_master_admin_monitoring_status_key
    CHECK (
        monitor_key IN (
            'peachweb',
            'peachbook',
            'square'
        )
    );


COMMENT ON TABLE master_admin_monitoring_status IS
    'Latest runtime health state for Master Admin operational '
    'monitors including PeachWeb, PeachBook, and external '
    'service providers.';


INSERT INTO master_admin_monitoring_status (
    monitor_key,
    status,
    status_text
)
VALUES (
    'square',
    'gray',
    'Not Checked'
)
ON CONFLICT (monitor_key)
DO NOTHING;


COMMIT;
