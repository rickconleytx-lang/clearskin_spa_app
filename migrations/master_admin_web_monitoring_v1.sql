BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- MASTER ADMIN WEB MONITORING V1
--
-- System-level canary targets for PeachWeb and PeachBook.
-- These settings are intentionally separate from per-user
-- Master Admin notification preferences.
--
-- Runtime health state is stored separately from configuration.
-- =========================================================


CREATE TABLE IF NOT EXISTS master_admin_monitoring_settings (

    master_admin_monitoring_setting_id BIGSERIAL PRIMARY KEY,

    singleton_key SMALLINT
        NOT NULL DEFAULT 1,

    peachweb_monitor_url VARCHAR(2048),

    peachbook_monitor_url VARCHAR(2048),

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

    CONSTRAINT uq_master_admin_monitoring_settings_singleton
        UNIQUE (singleton_key),

    CONSTRAINT chk_master_admin_monitoring_settings_singleton
        CHECK (singleton_key = 1),

    CONSTRAINT chk_master_admin_peachweb_monitor_url_nonblank
        CHECK (
            peachweb_monitor_url IS NULL
            OR LENGTH(TRIM(peachweb_monitor_url)) > 0
        ),

    CONSTRAINT chk_master_admin_peachbook_monitor_url_nonblank
        CHECK (
            peachbook_monitor_url IS NULL
            OR LENGTH(TRIM(peachbook_monitor_url)) > 0
        ),

    CONSTRAINT chk_master_admin_monitoring_settings_updated
        CHECK (
            updated_at >= created_at
        )
);


COMMENT ON TABLE master_admin_monitoring_settings IS
    'Singleton Peach Suite Pro Master Admin configuration for '
    'the PeachWeb and PeachBook canary monitor targets.';


COMMENT ON COLUMN
    master_admin_monitoring_settings.peachweb_monitor_url
IS
    'Public PeachWeb URL used as the platform canary target.';


COMMENT ON COLUMN
    master_admin_monitoring_settings.peachbook_monitor_url
IS
    'Public PeachBook URL used as the platform canary target.';


INSERT INTO master_admin_monitoring_settings (
    singleton_key
)
VALUES (1)
ON CONFLICT (singleton_key)
DO NOTHING;


CREATE TABLE IF NOT EXISTS master_admin_monitoring_status (

    monitor_key VARCHAR(32) PRIMARY KEY,

    status VARCHAR(16)
        NOT NULL DEFAULT 'gray',

    status_text VARCHAR(80)
        NOT NULL DEFAULT 'Not Checked',

    detail VARCHAR(500),

    checked_url VARCHAR(2048),

    http_status INTEGER,

    response_ms INTEGER,

    consecutive_failures INTEGER
        NOT NULL DEFAULT 0,

    last_checked_at TIMESTAMPTZ,

    last_success_at TIMESTAMPTZ,

    last_failure_at TIMESTAMPTZ,

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_master_admin_monitoring_status_key
        CHECK (
            monitor_key IN (
                'peachweb',
                'peachbook'
            )
        ),

    CONSTRAINT chk_master_admin_monitoring_status_value
        CHECK (
            status IN (
                'gray',
                'green',
                'yellow',
                'red'
            )
        ),

    CONSTRAINT chk_master_admin_monitoring_http_status
        CHECK (
            http_status IS NULL
            OR (
                http_status >= 100
                AND http_status <= 599
            )
        ),

    CONSTRAINT chk_master_admin_monitoring_response_ms
        CHECK (
            response_ms IS NULL
            OR response_ms >= 0
        ),

    CONSTRAINT chk_master_admin_monitoring_failures
        CHECK (
            consecutive_failures >= 0
        )
);


COMMENT ON TABLE master_admin_monitoring_status IS
    'Latest runtime health state for the configured PeachWeb '
    'and PeachBook Master Admin canary monitors.';


INSERT INTO master_admin_monitoring_status (
    monitor_key,
    status,
    status_text
)
VALUES
    ('peachweb', 'gray', 'Not Configured'),
    ('peachbook', 'gray', 'Not Configured')
ON CONFLICT (monitor_key)
DO NOTHING;


COMMIT;
