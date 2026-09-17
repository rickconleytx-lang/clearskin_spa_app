BEGIN;


-- ==========================================================
-- PEACH SUITE PRO
-- MASTER ADMIN MONITORING STATUS V4
--
-- Add Telnyx provider health to the generalized Master Admin
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
            'mailgun',
            'telnyx'
        )
    );


INSERT INTO master_admin_monitoring_status (
    monitor_key,
    status,
    status_text
)
VALUES (
    'telnyx',
    'gray',
    'Not Checked'
)
ON CONFLICT (monitor_key)
DO NOTHING;


COMMIT;
