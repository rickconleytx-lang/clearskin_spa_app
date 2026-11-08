BEGIN;

-- Peach Suite Pro
-- Event Units V1
-- Event Units are distinct from Provider Workspaces.

-- Support tenant-safe composite foreign keys.
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_business_units_spa_workspace
ON business_units (spa_id, business_unit_id);

CREATE TABLE IF NOT EXISTS event_units (

    event_unit_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    unit_name VARCHAR(150) NOT NULL,

    unit_type VARCHAR(30)
        NOT NULL DEFAULT 'truck',

    unit_identifier VARCHAR(80),

    description TEXT,

    calendar_color VARCHAR(7)
        NOT NULL DEFAULT '#E87929',

    is_active BOOLEAN
        NOT NULL DEFAULT TRUE,

    notes TEXT,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ,

    created_by INTEGER,
    updated_by INTEGER,

    CONSTRAINT fk_event_units_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_event_units_workspace
        FOREIGN KEY (spa_id, business_unit_id)
        REFERENCES business_units (
            spa_id, business_unit_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_event_units_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_event_units_updated_by
        FOREIGN KEY (updated_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT chk_event_units_name
        CHECK (LENGTH(BTRIM(unit_name)) > 0),

    CONSTRAINT chk_event_units_type
        CHECK (
            unit_type IN (
                'truck',
                'trailer',
                'cart',
                'booth',
                'custom'
            )
        ),

    CONSTRAINT chk_event_units_color
        CHECK (
            calendar_color ~
            '^#[0-9A-Fa-f]{6}$'
        )
);

-- Prevent duplicate names in the same workspace.
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_event_units_workspace_name
ON event_units (
    spa_id,
    business_unit_id,
    LOWER(BTRIM(unit_name))
);

-- Support tenant-safe event references later.
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_event_units_workspace_identity
ON event_units (
    spa_id,
    business_unit_id,
    event_unit_id
);

CREATE INDEX IF NOT EXISTS
    idx_event_units_workspace_active
ON event_units (
    spa_id,
    business_unit_id,
    is_active
);

COMMIT;
