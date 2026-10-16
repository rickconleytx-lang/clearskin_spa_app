BEGIN;

-- Add backup health without enabling reporting or notifications.
ALTER TABLE master_admin_monitoring_status
    DROP CONSTRAINT chk_master_admin_monitoring_status_key;

ALTER TABLE master_admin_monitoring_status
    ADD CONSTRAINT chk_master_admin_monitoring_status_key
    CHECK (
        monitor_key IN (
            'peachweb',
            'peachbook',
            'square',
            'mailgun',
            'telnyx',
            'backup'
        )
    );

INSERT INTO master_admin_monitoring_status (
    monitor_key,
    status,
    status_text
)
VALUES (
    'backup',
    'gray',
    'Not Configured'
)
ON CONFLICT (monitor_key)
DO NOTHING;

COMMIT;
