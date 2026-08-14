BEGIN;

-- =========================================================
-- SQUARE V2 SYNC ACTIVITY
--
-- Historical activity / retry trail for PSP -> Square master
-- data synchronization.
--
-- Enterprise safety:
--   spa_id + business_unit_id are always required.
--
-- Important:
--   This table does NOT perform synchronization itself.
--   Existing Client / Service / Inventory Square orchestrators
--   remain authoritative for actual Square writes.
-- =========================================================

CREATE TABLE IF NOT EXISTS square_sync_activity (
    square_sync_activity_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    square_connection_id BIGINT,
    environment VARCHAR(20) NOT NULL,

    entity_type VARCHAR(40) NOT NULL,
    entity_id BIGINT NOT NULL,

    trigger_action VARCHAR(40) NOT NULL,
    source VARCHAR(40) NOT NULL DEFAULT 'automatic',

    sync_status VARCHAR(40) NOT NULL DEFAULT 'pending',
    raw_status VARCHAR(40),
    result_action VARCHAR(80),

    square_object_id VARCHAR(255),
    square_parent_object_id VARCHAR(255),

    reason VARCHAR(255),
    message TEXT,

    attempt_number INTEGER NOT NULL DEFAULT 1,

    retry_of_activity_id BIGINT,
    requested_by INTEGER,

    requested_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_square_sync_activity_environment
        CHECK (
            environment IN (
                'sandbox',
                'production'
            )
        ),

    CONSTRAINT chk_square_sync_activity_entity_type
        CHECK (
            entity_type IN (
                'client',
                'service',
                'inventory_product'
            )
        ),

    CONSTRAINT chk_square_sync_activity_source
        CHECK (
            source IN (
                'automatic',
                'manual',
                'retry',
                'sync_all'
            )
        ),

    CONSTRAINT chk_square_sync_activity_status
        CHECK (
            sync_status IN (
                'pending',
                'successful',
                'failed',
                'needs_attention',
                'skipped'
            )
        ),

    CONSTRAINT chk_square_sync_activity_attempt
        CHECK (
            attempt_number >= 1
        ),

    CONSTRAINT fk_square_sync_activity_workspace
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_sync_activity_connection
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
        ON DELETE SET NULL (
            square_connection_id
        ),

    CONSTRAINT fk_square_sync_activity_retry
        FOREIGN KEY (
            retry_of_activity_id
        )
        REFERENCES square_sync_activity (
            square_sync_activity_id
        )
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS
    idx_square_sync_activity_workspace_recent
ON square_sync_activity (
    spa_id,
    business_unit_id,
    created_at DESC
);

CREATE INDEX IF NOT EXISTS
    idx_square_sync_activity_workspace_status
ON square_sync_activity (
    spa_id,
    business_unit_id,
    sync_status,
    created_at DESC
);

CREATE INDEX IF NOT EXISTS
    idx_square_sync_activity_workspace_entity
ON square_sync_activity (
    spa_id,
    business_unit_id,
    entity_type,
    entity_id,
    created_at DESC
);

CREATE INDEX IF NOT EXISTS
    idx_square_sync_activity_connection_environment
ON square_sync_activity (
    square_connection_id,
    environment,
    created_at DESC
)
WHERE square_connection_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS
    idx_square_sync_activity_actionable
ON square_sync_activity (
    spa_id,
    business_unit_id,
    sync_status,
    created_at DESC
)
WHERE sync_status IN (
    'failed',
    'needs_attention'
);

COMMIT;
