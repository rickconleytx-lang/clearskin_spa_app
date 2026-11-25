BEGIN;

-- Peach Suite Pro
-- Event Calendar Daily Operating Schedules V1
--
-- One schedule per event operating date.
-- Times are absolute timestamps, allowing overnight
-- operations and daylight-saving transitions.
-- Display times use the event's configured timezone.

CREATE TABLE IF NOT EXISTS event_calendar_daily_schedules (

    daily_schedule_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    event_id BIGINT NOT NULL,

    operating_date DATE NOT NULL,

    opens_at TIMESTAMPTZ NOT NULL,
    closes_at TIMESTAMPTZ NOT NULL,

    setup_at TIMESTAMPTZ,
    breakdown_at TIMESTAMPTZ,

    daily_notes TEXT,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ,

    created_by INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    updated_by INTEGER
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_event_daily_schedule_event
        FOREIGN KEY (
            spa_id, business_unit_id, event_id
        )
        REFERENCES event_calendar_events (
            spa_id, business_unit_id, event_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT uq_event_daily_by_date
        UNIQUE (
            spa_id,
            business_unit_id,
            event_id,
            operating_date
        ),

    CONSTRAINT chk_event_daily_hours
        CHECK (closes_at > opens_at),

    CONSTRAINT chk_event_daily_setup
        CHECK (
            setup_at IS NULL
            OR setup_at <= opens_at
        ),

    CONSTRAINT chk_event_daily_breakdown
        CHECK (
            breakdown_at IS NULL
            OR breakdown_at >= closes_at
        )
);

CREATE INDEX IF NOT EXISTS
    idx_event_daily_workspace_date
ON event_calendar_daily_schedules (
    spa_id,
    business_unit_id,
    operating_date
);

CREATE INDEX IF NOT EXISTS
    idx_event_daily_time_range
ON event_calendar_daily_schedules (
    opens_at,
    closes_at
);

COMMIT;
