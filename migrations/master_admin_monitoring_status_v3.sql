BEGIN;


-- ==========================================================
-- PEACH SUITE PRO
-- MASTER ADMIN MONITORING STATUS V3
--
-- Add Mailgun provider health to the generalized Master Admin
-- monitoring-status registry.
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
            'square',
            'mailgun'
        )
    );


INSERT INTO master_admin_monitoring_status (
    monitor_key,
    status,
    status_text
)
VALUES (
    'mailgun',
    'gray',
    'Not Checked'
)
ON CONFLICT (monitor_key)
DO NOTHING;


COMMIT;
