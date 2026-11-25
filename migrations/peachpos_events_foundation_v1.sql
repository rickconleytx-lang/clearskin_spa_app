BEGIN;

-- Peach Suite Pro
-- PeachPOS Event Calendar Foundation V1
--
-- Event details and business-defined custom fields.
-- Daily schedules, equipment assignments, and
-- employee shifts follow in separate migrations.

CREATE TABLE IF NOT EXISTS event_calendar_custom_labels (

    spa_id INTEGER NOT NULL
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    slot_number SMALLINT NOT NULL
        CHECK (slot_number BETWEEN 1 AND 3),

    field_label VARCHAR(100) NOT NULL,

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_by INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    PRIMARY KEY (spa_id, slot_number),

    CONSTRAINT chk_event_custom_label
        CHECK (LENGTH(BTRIM(field_label)) > 0)
);

-- Missing labels display as Default 1, 2, or 3.

CREATE TABLE IF NOT EXISTS event_calendar_events (

    event_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    event_name VARCHAR(200) NOT NULL,
    venue_name VARCHAR(200) NOT NULL,

    street_address VARCHAR(255) NOT NULL,
    address_line2 VARCHAR(255),

    city VARCHAR(120) NOT NULL,
    county VARCHAR(120),
    state VARCHAR(80) NOT NULL,
    zip_code VARCHAR(20) NOT NULL,

    parking_setup_location TEXT,

    start_date DATE NOT NULL,
    end_date DATE NOT NULL,

    timezone_name VARCHAR(80),

    contact_name VARCHAR(150),
    contact_phone VARCHAR(40),
    contact_email VARCHAR(254),

    permits_obtained BOOLEAN
        NOT NULL DEFAULT FALSE,

    event_status VARCHAR(20)
        NOT NULL DEFAULT 'scheduled',

    is_public BOOLEAN
        NOT NULL DEFAULT FALSE,

    public_description TEXT,

    notes_1 TEXT,
    notes_2 TEXT,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ,

    created_by INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    updated_by INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_event_calendar_workspace
        FOREIGN KEY (spa_id, business_unit_id)
        REFERENCES business_units (
            spa_id, business_unit_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT chk_event_dates
        CHECK (end_date >= start_date),

    CONSTRAINT chk_event_name
        CHECK (LENGTH(BTRIM(event_name)) > 0),

    CONSTRAINT chk_event_status
        CHECK (
            event_status IN (
                'scheduled',
                'confirmed',
                'cancelled',
                'completed'
            )
        )
);

-- Composite identity allows future tenant-safe
-- child tables and employee assignments.

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_event_calendar_workspace_identity
ON event_calendar_events (
    spa_id, business_unit_id, event_id
);

CREATE INDEX IF NOT EXISTS
    idx_event_calendar_workspace_dates
ON event_calendar_events (
    spa_id, business_unit_id, start_date, end_date
);

CREATE INDEX IF NOT EXISTS
    idx_event_calendar_workspace_status
ON event_calendar_events (
    spa_id, business_unit_id, event_status
);

-- Values are stored per event, with a snapshot
-- of the label used when the value was saved.
-- Renaming a business label does not reinterpret
-- previously saved event values.

CREATE TABLE IF NOT EXISTS event_calendar_custom_values (

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    event_id BIGINT NOT NULL,

    slot_number SMALLINT NOT NULL
        CHECK (slot_number BETWEEN 1 AND 3),

    field_label_snapshot VARCHAR(100) NOT NULL,
    field_value TEXT NOT NULL,

    PRIMARY KEY (
        spa_id, business_unit_id,
        event_id, slot_number
    ),

    CONSTRAINT fk_event_custom_values_event
        FOREIGN KEY (
            spa_id, business_unit_id, event_id
        )
        REFERENCES event_calendar_events (
            spa_id, business_unit_id, event_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT chk_event_custom_snapshot_label
        CHECK (
            LENGTH(BTRIM(field_label_snapshot)) > 0
        )
);

COMMIT;
