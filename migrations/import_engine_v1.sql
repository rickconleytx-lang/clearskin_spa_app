BEGIN;

-- =========================================================
-- PEACH SUITE PRO SHARED IMPORT ENGINE V1
--
-- Persistent import orchestration for CSV/XLSX imports.
--
-- Architecture:
--   import_runs
--     One durable upload/import workflow.
--
--   import_run_rows
--     One staged source row per uploaded record.
--
-- Entity-specific services remain authoritative for validation,
-- duplicate rules, and final database writes.
--
-- Enterprise safety:
--   spa_id + business_unit_id are always required.
-- =========================================================


CREATE TABLE IF NOT EXISTS import_runs (

    import_run_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,

    business_unit_id INTEGER NOT NULL,

    entity_type VARCHAR(50) NOT NULL,

    run_status VARCHAR(30)
        NOT NULL DEFAULT 'mapping',

    source_filename VARCHAR(255) NOT NULL,

    source_extension VARCHAR(10) NOT NULL,

    source_size_bytes BIGINT NOT NULL,

    source_sha256 VARCHAR(64) NOT NULL,

    mapping_json JSONB
        NOT NULL DEFAULT '{}'::jsonb,

    options_json JSONB
        NOT NULL DEFAULT '{}'::jsonb,

    total_rows INTEGER
        NOT NULL DEFAULT 0,

    valid_rows INTEGER
        NOT NULL DEFAULT 0,

    invalid_rows INTEGER
        NOT NULL DEFAULT 0,

    strong_duplicate_rows INTEGER
        NOT NULL DEFAULT 0,

    possible_duplicate_rows INTEGER
        NOT NULL DEFAULT 0,

    imported_rows INTEGER
        NOT NULL DEFAULT 0,

    skipped_rows INTEGER
        NOT NULL DEFAULT 0,

    error_rows INTEGER
        NOT NULL DEFAULT 0,

    failure_message TEXT,

    requested_by INTEGER,

    requested_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    started_at TIMESTAMPTZ,

    last_activity_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    completed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_import_runs_status
        CHECK (
            run_status IN (
                'mapping',
                'review',
                'ready',
                'importing',
                'completed',
                'failed',
                'cancelled'
            )
        ),

    CONSTRAINT chk_import_runs_extension
        CHECK (
            source_extension IN (
                'csv',
                'xlsx'
            )
        ),

    CONSTRAINT chk_import_runs_source_size
        CHECK (
            source_size_bytes > 0
        ),

    CONSTRAINT chk_import_runs_counters
        CHECK (
            total_rows >= 0
            AND valid_rows >= 0
            AND invalid_rows >= 0
            AND strong_duplicate_rows >= 0
            AND possible_duplicate_rows >= 0
            AND imported_rows >= 0
            AND skipped_rows >= 0
            AND error_rows >= 0
        ),

    CONSTRAINT fk_import_runs_workspace
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_import_runs_requested_by
        FOREIGN KEY (
            requested_by
        )
        REFERENCES users (
            user_id
        )
        ON DELETE SET NULL
);


CREATE TABLE IF NOT EXISTS import_run_rows (

    import_run_row_id BIGSERIAL PRIMARY KEY,

    import_run_id BIGINT NOT NULL,

    spa_id INTEGER NOT NULL,

    business_unit_id INTEGER NOT NULL,

    source_row_number INTEGER NOT NULL,

    source_data JSONB
        NOT NULL DEFAULT '{}'::jsonb,

    mapped_data JSONB
        NOT NULL DEFAULT '{}'::jsonb,

    validation_status VARCHAR(20)
        NOT NULL DEFAULT 'pending',

    validation_errors JSONB
        NOT NULL DEFAULT '[]'::jsonb,

    duplicate_status VARCHAR(20)
        NOT NULL DEFAULT 'not_checked',

    duplicate_details JSONB
        NOT NULL DEFAULT '[]'::jsonb,

    import_status VARCHAR(20)
        NOT NULL DEFAULT 'pending',

    imported_record_id BIGINT,

    error_message TEXT,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_import_run_rows_source_row
        CHECK (
            source_row_number >= 2
        ),

    CONSTRAINT chk_import_run_rows_validation
        CHECK (
            validation_status IN (
                'pending',
                'valid',
                'invalid'
            )
        ),

    CONSTRAINT chk_import_run_rows_duplicate
        CHECK (
            duplicate_status IN (
                'not_checked',
                'none',
                'strong',
                'possible'
            )
        ),

    CONSTRAINT chk_import_run_rows_import
        CHECK (
            import_status IN (
                'pending',
                'imported',
                'skipped',
                'error'
            )
        ),

    CONSTRAINT fk_import_run_rows_run
        FOREIGN KEY (
            import_run_id
        )
        REFERENCES import_runs (
            import_run_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_import_run_rows_workspace
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE,

    CONSTRAINT uq_import_run_rows_source_row
        UNIQUE (
            import_run_id,
            source_row_number
        )
);


CREATE INDEX IF NOT EXISTS
    idx_import_runs_workspace_recent
ON import_runs (
    spa_id,
    business_unit_id,
    created_at DESC
);


CREATE INDEX IF NOT EXISTS
    idx_import_runs_workspace_status
ON import_runs (
    spa_id,
    business_unit_id,
    entity_type,
    run_status,
    updated_at DESC
);


CREATE INDEX IF NOT EXISTS
    idx_import_runs_source_hash
ON import_runs (
    spa_id,
    business_unit_id,
    entity_type,
    source_sha256
);


CREATE INDEX IF NOT EXISTS
    idx_import_run_rows_run
ON import_run_rows (
    import_run_id,
    source_row_number
);


CREATE INDEX IF NOT EXISTS
    idx_import_run_rows_review
ON import_run_rows (
    import_run_id,
    validation_status,
    duplicate_status,
    import_status
);


COMMIT;
