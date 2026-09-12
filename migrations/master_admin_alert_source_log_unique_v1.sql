BEGIN;

DROP INDEX IF EXISTS
    master_admin_alert_events_source_log_idx;

CREATE UNIQUE INDEX
    uq_master_admin_alert_events_source_log
ON master_admin_alert_events (
    source_log_id
)
WHERE source_log_id IS NOT NULL;

COMMENT ON INDEX
    uq_master_admin_alert_events_source_log
IS
    'A committed System Activity log may reserve at most one '
    'Master Admin alert event. Prevents duplicate alert creation '
    'if the same source log is replayed or reprocessed.';

COMMIT;
