BEGIN;

-- =========================================================
-- SQUARE V2 PACKETIZED SYNC ALL RUNS
--
-- Persistent orchestration state for PSP -> Square Sync All.
--
-- Enterprise safety:
--   spa_id + business_unit_id are always required.
--
-- Important:
--   This table does NOT perform synchronization itself.
--   Existing Client / Service / Inventory Square orchestrators
--   remain authoritative for actual Square writes.
--
--   The run stores only bounded orchestration state. Entity
--   IDs are not stored as a list. Keyset cursors plus frozen
--   upper ID bounds allow Sync All to advance in small packets.
-- =========================================================

CREATE TABLE IF NOT EXISTS square_sync_runs (
    square_sync_run_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    square_connection_id BIGINT NOT NULL,
    environment VARCHAR(20) NOT NULL,

    run_status VARCHAR(30)
        NOT NULL DEFAULT 'running',

    current_phase VARCHAR(40)
        NOT NULL DEFAULT 'client',

    packet_size INTEGER
        NOT NULL DEFAULT 10,

    client_cursor BIGINT
        NOT NULL DEFAULT 0,

    service_cursor BIGINT
        NOT NULL DEFAULT 0,

    inventory_product_cursor BIGINT
        NOT NULL DEFAULT 0,

    client_max_id BIGINT
        NOT NULL DEFAULT 0,

    service_max_id BIGINT
        NOT NULL DEFAULT 0,

    inventory_product_max_id BIGINT
        NOT NULL DEFAULT 0,

    client_total INTEGER
        NOT NULL DEFAULT 0,

    service_total INTEGER
        NOT NULL DEFAULT 0,

    inventory_product_total INTEGER
        NOT NULL DEFAULT 0,

    client_synced INTEGER
        NOT NULL DEFAULT 0,

    client_needs_attention INTEGER
        NOT NULL DEFAULT 0,

    client_error INTEGER
        NOT NULL DEFAULT 0,

    client_skipped INTEGER
        NOT NULL DEFAULT 0,

    service_synced INTEGER
        NOT NULL DEFAULT 0,

    service_needs_attention INTEGER
        NOT NULL DEFAULT 0,

    service_error INTEGER
        NOT NULL DEFAULT 0,

    service_skipped INTEGER
        NOT NULL DEFAULT 0,

    inventory_product_synced INTEGER
        NOT NULL DEFAULT 0,

    inventory_product_needs_attention INTEGER
        NOT NULL DEFAULT 0,

    inventory_product_error INTEGER
        NOT NULL DEFAULT 0,

    inventory_product_skipped INTEGER
        NOT NULL DEFAULT 0,

    activity_log_failures INTEGER
        NOT NULL DEFAULT 0,

    failure_message TEXT,

    requested_by INTEGER,

    requested_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    started_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    last_activity_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    completed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_square_sync_runs_environment
        CHECK (
            environment IN (
                'sandbox',
                'production'
            )
        ),

    CONSTRAINT chk_square_sync_runs_status
        CHECK (
            run_status IN (
                'running',
                'completed',
                'failed',
                'stale'
            )
        ),

    CONSTRAINT chk_square_sync_runs_phase
        CHECK (
            current_phase IN (
                'client',
                'service',
                'inventory_product',
                'completed'
            )
        ),

    CONSTRAINT chk_square_sync_runs_packet_size
        CHECK (
            packet_size BETWEEN 1 AND 50
        ),

    CONSTRAINT chk_square_sync_runs_cursors
        CHECK (
            client_cursor >= 0
            AND service_cursor >= 0
            AND inventory_product_cursor >= 0
            AND client_max_id >= 0
            AND service_max_id >= 0
            AND inventory_product_max_id >= 0
        ),

    CONSTRAINT chk_square_sync_runs_totals
        CHECK (
            client_total >= 0
            AND service_total >= 0
            AND inventory_product_total >= 0
        ),

    CONSTRAINT chk_square_sync_runs_counters
        CHECK (
            client_synced >= 0
            AND client_needs_attention >= 0
            AND client_error >= 0
            AND client_skipped >= 0
            AND service_synced >= 0
            AND service_needs_attention >= 0
            AND service_error >= 0
            AND service_skipped >= 0
            AND inventory_product_synced >= 0
            AND inventory_product_needs_attention >= 0
            AND inventory_product_error >= 0
            AND inventory_product_skipped >= 0
            AND activity_log_failures >= 0
        ),

    CONSTRAINT fk_square_sync_runs_workspace
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_sync_runs_connection
        FOREIGN KEY (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        )
        REFERENCES square_connections (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_sync_runs_requested_by
        FOREIGN KEY (
            requested_by
        )
        REFERENCES users (
            user_id
        )
        ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_square_sync_runs_active_workspace
ON square_sync_runs (
    spa_id,
    business_unit_id,
    environment
)
WHERE run_status = 'running';

CREATE INDEX IF NOT EXISTS
    idx_square_sync_runs_workspace_recent
ON square_sync_runs (
    spa_id,
    business_unit_id,
    created_at DESC
);

CREATE INDEX IF NOT EXISTS
    idx_square_sync_runs_workspace_status
ON square_sync_runs (
    spa_id,
    business_unit_id,
    environment,
    run_status,
    updated_at DESC
);

COMMIT;
