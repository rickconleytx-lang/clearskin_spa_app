BEGIN;

CREATE TABLE master_admin_backup_sources (
    source_key VARCHAR(64) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    timezone_name VARCHAR(64) NOT NULL DEFAULT 'America/Chicago',
    schedule_hour SMALLINT NOT NULL DEFAULT 22
        CHECK (schedule_hour BETWEEN 0 AND 23),
    grace_minutes INTEGER NOT NULL DEFAULT 60
        CHECK (grace_minutes BETWEEN 5 AND 1440),
    last_received_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE master_admin_backup_reports (
    backup_report_id BIGSERIAL PRIMARY KEY,
    source_key VARCHAR(64) NOT NULL
        REFERENCES master_admin_backup_sources(source_key),
    report_uuid UUID NOT NULL,
    reported_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_started_at TIMESTAMPTZ,
    run_finished_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    run_status VARCHAR(16) NOT NULL
        CHECK (run_status IN ('running', 'success', 'failed', 'idle')),
    icloud_status VARCHAR(16) NOT NULL
        CHECK (icloud_status IN ('unknown', 'success', 'failed')),
    peachvault_status VARCHAR(16) NOT NULL
        CHECK (peachvault_status IN ('unknown', 'success', 'failed')),
    failure_code VARCHAR(64),
    UNIQUE (source_key, report_uuid),
    CHECK (
        run_status <> 'success'
        OR (
            icloud_status = 'success'
            AND peachvault_status = 'success'
            AND run_started_at IS NOT NULL
            AND run_finished_at IS NOT NULL
            AND last_success_at IS NOT NULL
        )
    ),
    CHECK (
        run_finished_at IS NULL
        OR (
            run_started_at IS NOT NULL
            AND run_finished_at >= run_started_at
        )
    )
);

CREATE INDEX master_admin_backup_reports_recent_idx
    ON master_admin_backup_reports(source_key, received_at DESC);

CREATE TABLE master_admin_backup_incidents (
    backup_incident_id BIGSERIAL PRIMARY KEY,
    source_key VARCHAR(64) NOT NULL
        REFERENCES master_admin_backup_sources(source_key),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    reason_code VARCHAR(64) NOT NULL,
    icloud_failed BOOLEAN NOT NULL DEFAULT FALSE,
    peachvault_failed BOOLEAN NOT NULL DEFAULT FALSE,
    CHECK (updated_at >= opened_at),
    CHECK (resolved_at IS NULL OR resolved_at >= opened_at)
);

CREATE UNIQUE INDEX master_admin_backup_one_open_incident_idx
    ON master_admin_backup_incidents(source_key)
    WHERE resolved_at IS NULL;

-- Durable outbox: save each transition in the incident transaction.
-- Reservation may be retried safely until linked to an alert event.
CREATE TABLE master_admin_backup_notifications (
    backup_notification_id BIGSERIAL PRIMARY KEY,
    backup_incident_id BIGINT NOT NULL
        REFERENCES master_admin_backup_incidents(backup_incident_id),
    transition VARCHAR(16) NOT NULL
        CHECK (transition IN ('failure', 'recovery')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    alert_event_id BIGINT UNIQUE
        REFERENCES master_admin_alert_events(master_admin_alert_event_id),
    UNIQUE (backup_incident_id, transition)
);

COMMENT ON TABLE master_admin_backup_reports IS
    'Backup metadata only. Never store credentials, database contents, '
    'raw logs, or unrestricted reporter text.';

COMMENT ON TABLE master_admin_backup_notifications IS
    'Transactional backup transition outbox; reservation must link the '
    'alert event atomically to prevent duplicate notifications.';

COMMIT;
