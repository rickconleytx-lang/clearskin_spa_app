BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- MASTER ADMIN NOTIFICATION SETTINGS V1
--
-- Per-Master-Admin operational and security alert settings.
--
-- Notification destinations are intentionally separate from:
--   users.email      -> business-login identity
--   users.sms_phone  -> personal account/security phone
--
-- A NULL notification destination means the application may
-- fall back to the corresponding existing user contact field.
--
-- Delivery channels default OFF until deliberately enabled.
-- Alert categories default ON so enabling a delivery channel
-- immediately uses Peach Suite Pro's recommended alert policy.
-- =========================================================


CREATE TABLE IF NOT EXISTS master_admin_notification_settings (

    master_admin_notification_setting_id BIGSERIAL PRIMARY KEY,

    user_id INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    notification_email VARCHAR(320),

    notification_phone VARCHAR(25),

    notification_email_verified_at TIMESTAMPTZ,

    notification_phone_verified_at TIMESTAMPTZ,

    email_alerts_enabled BOOLEAN
        NOT NULL DEFAULT FALSE,

    sms_alerts_enabled BOOLEAN
        NOT NULL DEFAULT FALSE,

    security_alerts_enabled BOOLEAN
        NOT NULL DEFAULT TRUE,

    system_integration_alerts_enabled BOOLEAN
        NOT NULL DEFAULT TRUE,

    account_lockout_alerts_enabled BOOLEAN
        NOT NULL DEFAULT TRUE,

    system_health_alerts_enabled BOOLEAN
        NOT NULL DEFAULT TRUE,

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

    CONSTRAINT uq_master_admin_notification_settings_user
        UNIQUE (user_id),

    CONSTRAINT chk_master_admin_notification_email_nonblank
        CHECK (
            notification_email IS NULL
            OR LENGTH(TRIM(notification_email)) > 0
        ),

    CONSTRAINT chk_master_admin_notification_phone_nonblank
        CHECK (
            notification_phone IS NULL
            OR LENGTH(TRIM(notification_phone)) > 0
        ),

    CONSTRAINT chk_master_admin_notification_settings_updated
        CHECK (
            updated_at >= created_at
        )

);


COMMENT ON TABLE master_admin_notification_settings IS
    'Per-user Peach Suite Pro Master Admin operational and '
    'security alert destinations and preferences.';


COMMENT ON COLUMN
    master_admin_notification_settings.notification_email
IS
    'Optional operational-alert email override. NULL allows '
    'the application to use the Master Admin Login Email.';


COMMENT ON COLUMN
    master_admin_notification_settings.notification_phone
IS
    'Optional operational-alert SMS destination. NULL allows '
    'the application to use the Master Admin Personal Mobile Phone. '
    'This field does not configure or change MFA.';


COMMENT ON COLUMN
    master_admin_notification_settings.notification_email_verified_at
IS
    'Time the dedicated notification email was verified. '
    'NULL means no dedicated verified destination is active.';


COMMENT ON COLUMN
    master_admin_notification_settings.notification_phone_verified_at
IS
    'Time the dedicated notification phone was verified. '
    'NULL means no dedicated verified destination is active.';


COMMENT ON COLUMN
    master_admin_notification_settings.email_alerts_enabled
IS
    'Whether qualifying Master Admin alerts may be delivered '
    'by email. Defaults to disabled until deliberately enabled.';


COMMENT ON COLUMN
    master_admin_notification_settings.sms_alerts_enabled
IS
    'Whether qualifying Master Admin alerts may be delivered '
    'by SMS. Defaults to disabled until deliberately enabled.';


COMMENT ON COLUMN
    master_admin_notification_settings.security_alerts_enabled
IS
    'Whether qualifying security events are eligible for '
    'Master Admin alert delivery.';


COMMENT ON COLUMN
    master_admin_notification_settings.system_integration_alerts_enabled
IS
    'Whether qualifying system and integration failures are '
    'eligible for Master Admin alert delivery.';


COMMENT ON COLUMN
    master_admin_notification_settings.account_lockout_alerts_enabled
IS
    'Whether qualifying account lockout events are eligible '
    'for Master Admin alert delivery.';


COMMENT ON COLUMN
    master_admin_notification_settings.system_health_alerts_enabled
IS
    'Whether qualifying system-health degradation events are '
    'eligible for Master Admin alert delivery.';


COMMIT;
