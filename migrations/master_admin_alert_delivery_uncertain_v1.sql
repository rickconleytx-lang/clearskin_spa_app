BEGIN;

ALTER TABLE master_admin_alert_deliveries
    DROP CONSTRAINT chk_master_admin_alert_delivery_status;

ALTER TABLE master_admin_alert_deliveries
    ADD CONSTRAINT chk_master_admin_alert_delivery_status
    CHECK (
        status IN (
            'pending',
            'attempting',
            'sent',
            'failed',
            'skipped',
            'uncertain'
        )
    );

COMMENT ON COLUMN
    master_admin_alert_deliveries.status
IS
    'Delivery lifecycle: pending, attempting, sent, failed, skipped, '
    'or uncertain. Uncertain means provider delivery may have occurred '
    'but PSP could not safely confirm/finalize the result; do not '
    'automatically retry.';

COMMIT;
