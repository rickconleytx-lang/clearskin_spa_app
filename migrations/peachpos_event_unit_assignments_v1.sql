BEGIN;

-- Peach Suite Pro
-- Event Calendar Equipment Assignments V1
--
-- Apply AFTER:
-- 1. peachpos_events_foundation_v1.sql
-- 2. peachpos_event_daily_schedules_v1.sql
--
-- btree_gist provides GiST equality operators for integer IDs.
-- Verify extension support in each target environment first.

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Composite identity for tenant-safe daily schedule references.

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_event_daily_schedule_scope
ON event_calendar_daily_schedules (
    spa_id,
    business_unit_id,
    event_id,
    daily_schedule_id
);

CREATE TABLE IF NOT EXISTS event_calendar_unit_assignments (

    unit_assignment_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    event_id BIGINT NOT NULL,
    daily_schedule_id BIGINT NOT NULL,
    event_unit_id BIGINT NOT NULL,

    -- Equipment occupancy interval.
    -- Include setup/breakdown when applicable.
    assigned_start_at TIMESTAMPTZ NOT NULL,
    assigned_end_at TIMESTAMPTZ NOT NULL,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ,

    created_by INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    updated_by INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_event_unit_assignment_schedule
        FOREIGN KEY (
            spa_id,
            business_unit_id,
            event_id,
            daily_schedule_id
        )
        REFERENCES event_calendar_daily_schedules (
            spa_id,
            business_unit_id,
            event_id,
            daily_schedule_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_event_unit_assignment_equipment
        FOREIGN KEY (
            spa_id,
            business_unit_id,
            event_unit_id
        )
        REFERENCES event_units (
            spa_id,
            business_unit_id,
            event_unit_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT chk_event_unit_assignment_times
        CHECK (assigned_end_at > assigned_start_at),

    -- Active reservations for the same physical unit
    -- must not overlap, even across different events.
    -- The half-open interval permits back-to-back bookings.

    CONSTRAINT excl_event_unit_assignment_overlap
        EXCLUDE USING gist (
            spa_id WITH =,
            event_unit_id WITH =,
            tstzrange(
                assigned_start_at,
                assigned_end_at,
                '[)'
            ) WITH &&
        )
        WHERE (is_active)
);

-- One active assignment per equipment unit per daily schedule.
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_event_unit_assignment_active_schedule
ON event_calendar_unit_assignments (
    spa_id,
    business_unit_id,
    daily_schedule_id,
    event_unit_id
)
WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS
    idx_event_unit_assignment_daily
ON event_calendar_unit_assignments (
    spa_id,
    business_unit_id,
    event_id,
    daily_schedule_id
);

COMMIT;
