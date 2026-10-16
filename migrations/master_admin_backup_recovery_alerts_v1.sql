BEGIN;

ALTER TABLE master_admin_alert_events
    DROP CONSTRAINT chk_master_admin_alert_event_severity;

ALTER TABLE master_admin_alert_events
    ADD CONSTRAINT chk_master_admin_alert_event_severity
    CHECK (
        severity IN ('WARNING', 'ERROR', 'ALERT')
        OR (
            severity = 'INFO'
            AND COALESCE(
                alert_category = 'system_health'
                AND source_category = 'SYSTEM'
                AND source_related_type = 'backup_recovery',
                FALSE
            )
        )
    );

COMMENT ON CONSTRAINT chk_master_admin_alert_event_severity
ON master_admin_alert_events IS
    'INFO is allowed only for explicit System Health backup recovery '
    'notifications; other alerts retain WARNING/ERROR/ALERT severity.';

COMMIT;
