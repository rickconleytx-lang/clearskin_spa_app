BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- MASTER ADMIN ALERTING V1
--
-- Durable reservation, cooldown, and delivery tracking for
-- proactive Master Admin operational/security alerts.
--
-- Alert events may reference system_logs, but system-log
-- retention must remain free to delete old log records.
--
-- Notification destinations themselves are NOT stored here.
-- =========================================================


CREATE TABLE IF NOT EXISTS master_admin_alert_events (

    master_admin_alert_event_id BIGSERIAL PRIMARY KEY,

    master_admin_user_id INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    source_log_id INTEGER
        REFERENCES system_logs(log_id)
        ON DELETE SET NULL,

    alert_category VARCHAR(32) NOT NULL,

    alert_key VARCHAR(128) NOT NULL,

    fingerprint CHAR(64) NOT NULL,

    severity VARCHAR(16) NOT NULL,

    source_category VARCHAR(64),

    source_related_type VARCHAR(128),

    alert_title VARCHAR(180) NOT NULL,

    alert_message TEXT NOT NULL,

    cooldown_minutes INTEGER
        NOT NULL DEFAULT 60,

    reserved_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    completed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_master_admin_alert_event_category
        CHECK (
            alert_category IN (
                'security',
                'system_integration',
                'account_lockout',
                'system_health'
            )
        ),

    CONSTRAINT chk_master_admin_alert_event_severity
        CHECK (
            severity IN (
                'WARNING',
                'ERROR',
                'ALERT'
            )
        ),

    CONSTRAINT chk_master_admin_alert_event_cooldown
        CHECK (
            cooldown_minutes >= 1
            AND cooldown_minutes <= 10080
        ),

    CONSTRAINT chk_master_admin_alert_event_completed
        CHECK (
            completed_at IS NULL
            OR completed_at >= reserved_at
        ),

    CONSTRAINT chk_master_admin_alert_event_updated
        CHECK (
            updated_at >= created_at
        )

);


CREATE INDEX IF NOT EXISTS
    master_admin_alert_events_fingerprint_idx
ON master_admin_alert_events (
    master_admin_user_id,
    fingerprint,
    reserved_at DESC
);


CREATE INDEX IF NOT EXISTS
    master_admin_alert_events_source_log_idx
ON master_admin_alert_events (
    source_log_id
)
WHERE source_log_id IS NOT NULL;


CREATE INDEX IF NOT EXISTS
    master_admin_alert_events_recent_idx
ON master_admin_alert_events (
    reserved_at DESC
);


CREATE TABLE IF NOT EXISTS master_admin_alert_deliveries (

    master_admin_alert_delivery_id BIGSERIAL PRIMARY KEY,

    master_admin_alert_event_id BIGINT NOT NULL
        REFERENCES master_admin_alert_events(
            master_admin_alert_event_id
        )
        ON DELETE CASCADE,

    channel VARCHAR(16) NOT NULL,

    destination_source VARCHAR(32),

    status VARCHAR(24)
        NOT NULL DEFAULT 'pending',

    provider_message_id VARCHAR(255),

    error_summary TEXT,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    attempted_at TIMESTAMPTZ,

    sent_at TIMESTAMPTZ,

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_master_admin_alert_delivery
        UNIQUE (
            master_admin_alert_event_id,
            channel
        ),

    CONSTRAINT chk_master_admin_alert_delivery_channel
        CHECK (
            channel IN (
                'email',
                'sms'
            )
        ),

    CONSTRAINT chk_master_admin_alert_destination_source
        CHECK (
            destination_source IS NULL
            OR destination_source IN (
                'login_email',
                'notification_email',
                'personal_mobile',
                'notification_phone'
            )
        ),

    CONSTRAINT chk_master_admin_alert_delivery_status
        CHECK (
            status IN (
                'pending',
                'attempting',
                'sent',
                'failed',
                'skipped'
            )
        ),

    CONSTRAINT chk_master_admin_alert_delivery_attempted
        CHECK (
            attempted_at IS NULL
            OR attempted_at >= created_at
        ),

    CONSTRAINT chk_master_admin_alert_delivery_sent
        CHECK (
            sent_at IS NULL
            OR (
                attempted_at IS NOT NULL
                AND sent_at >= attempted_at
            )
        ),

    CONSTRAINT chk_master_admin_alert_delivery_updated
        CHECK (
            updated_at >= created_at
        )

);


CREATE INDEX IF NOT EXISTS
    master_admin_alert_deliveries_status_idx
ON master_admin_alert_deliveries (
    status,
    created_at DESC
);


COMMENT ON TABLE master_admin_alert_events IS
    'Durable Master Admin operational/security alert '
    'reservations. The fingerprint and cooldown window prevent '
    'duplicate alert storms.';


COMMENT ON COLUMN master_admin_alert_events.source_log_id IS
    'Optional originating system_logs row. ON DELETE SET NULL '
    'allows normal System Activity retention to continue.';


COMMENT ON COLUMN master_admin_alert_events.fingerprint IS
    'SHA-256 hexadecimal fingerprint used with the Master Admin '
    'user and cooldown window to suppress duplicate alerts.';


COMMENT ON COLUMN master_admin_alert_events.alert_message IS
    'Sanitized Master Admin alert text. Do not store passwords, '
    'verification codes, raw credentials, or notification '
    'destination values in this field.';


COMMENT ON TABLE master_admin_alert_deliveries IS
    'Per-channel delivery state for a Master Admin alert event. '
    'Actual email addresses and phone numbers are intentionally '
    'not stored in this table.';


COMMENT ON COLUMN
    master_admin_alert_deliveries.destination_source
IS
    'Identifies which secured profile destination was used '
    'without storing the destination value itself.';


COMMENT ON COLUMN
    master_admin_alert_deliveries.error_summary
IS
    'Sanitized delivery failure summary. Do not store message '
    'bodies, credentials, email addresses, or phone numbers.';


COMMIT;
