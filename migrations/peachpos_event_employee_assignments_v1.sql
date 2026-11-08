BEGIN;

-- Peach Suite Pro
-- Event Calendar Employee Assignments V1
--
-- Apply after Event Foundation, Daily Schedules,
-- and Equipment Assignments.
--
-- These are scheduling records ONLY.
-- No payroll entries, deductions, or payments
-- are created by this table.

-- Composite identity for optional equipment assignments.

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_event_unit_assignment_employee_reference
ON event_calendar_unit_assignments (
    spa_id,
    business_unit_id,
    event_id,
    daily_schedule_id,
    unit_assignment_id
);

CREATE TABLE IF NOT EXISTS event_calendar_employee_assignments (

    employee_assignment_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    event_id BIGINT NOT NULL,
    daily_schedule_id BIGINT NOT NULL,

    employee_id INTEGER NOT NULL,

    -- Optional assignment to one physical event unit.
    unit_assignment_id BIGINT,

    shift_start_at TIMESTAMPTZ NOT NULL,
    shift_end_at TIMESTAMPTZ NOT NULL,

    shift_role VARCHAR(100),
    shift_notes TEXT,

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

    -- Employee must belong to the same business
    -- and Provider Workspace.

    CONSTRAINT fk_event_employee_workspace
        FOREIGN KEY (
            spa_id,
            business_unit_id,
            employee_id
        )
        REFERENCES employee_business_unit_memberships (
            spa_id,
            business_unit_id,
            employee_id
        )
        ON DELETE RESTRICT,

    -- Assignment must refer to the correct event day.

    CONSTRAINT fk_event_employee_daily_schedule
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

    -- If equipment is selected, it must belong to
    -- the same event and daily schedule.

    CONSTRAINT fk_event_employee_equipment
        FOREIGN KEY (
            spa_id,
            business_unit_id,
            event_id,
            daily_schedule_id,
            unit_assignment_id
        )
        REFERENCES event_calendar_unit_assignments (
            spa_id,
            business_unit_id,
            event_id,
            daily_schedule_id,
            unit_assignment_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT chk_event_employee_shift_times
        CHECK (shift_end_at > shift_start_at),

    -- Block overlapping active shifts for the same
    -- employee across events and Provider Workspaces
    -- within the same business.
    --
    -- Half-open intervals permit adjacent shifts.

    CONSTRAINT excl_event_employee_shift_overlap
        EXCLUDE USING gist (
            spa_id WITH =,
            employee_id WITH =,
            tstzrange(
                shift_start_at,
                shift_end_at,
                '[)'
            ) WITH &&
        )
        WHERE (is_active)
);

CREATE INDEX IF NOT EXISTS
    idx_event_employee_daily_schedule
ON event_calendar_employee_assignments (
    spa_id,
    business_unit_id,
    event_id,
    daily_schedule_id
);

CREATE INDEX IF NOT EXISTS
    idx_event_employee_schedule_lookup
ON event_calendar_employee_assignments (
    spa_id,
    employee_id,
    shift_start_at
);

COMMIT;
