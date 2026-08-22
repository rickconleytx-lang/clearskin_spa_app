BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- SQUARE WORKSPACE SETTINGS V1
--
-- Workspace-level Square operating behavior.
--
-- These settings are intentionally separate from
-- square_connections because connection records are
-- environment-specific (sandbox / production), while the
-- business operating mode belongs to the PSP workspace.
--
-- Existing workspaces retain Appointment / Service behavior
-- unless a user explicitly changes the setting.
-- =========================================================


CREATE TABLE IF NOT EXISTS square_workspace_settings (

    square_workspace_setting_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    processing_mode VARCHAR(40)
        NOT NULL DEFAULT 'appointment_service',

    track_inventory_sales BOOLEAN
        NOT NULL DEFAULT TRUE,

    created_by INTEGER,
    updated_by INTEGER,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_square_workspace_processing_mode
        CHECK (
            processing_mode IN (
                'appointment_service',
                'pos_daily_sales'
            )
        ),

    CONSTRAINT fk_square_workspace_settings_workspace
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_workspace_settings_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_square_workspace_settings_updated_by
        FOREIGN KEY (updated_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT uq_square_workspace_settings_workspace
        UNIQUE (
            spa_id,
            business_unit_id
        )
);


COMMENT ON COLUMN
    square_workspace_settings.processing_mode
IS
    'Workspace Square operating mode. appointment_service '
    'uses appointment/client/service reconciliation. '
    'pos_daily_sales supports automatic POS sales posting '
    'and daily financial summaries.';


COMMENT ON COLUMN
    square_workspace_settings.track_inventory_sales
IS
    'Controls whether item-level Square retail sales create '
    'PSP inventory movements. Financial transaction history '
    'is retained regardless of this setting.';


COMMIT;
