BEGIN;

-- =========================================================
-- 1. BOOKING SETTINGS
-- One settings record per Provider Workspace.
-- =========================================================

CREATE TABLE IF NOT EXISTS booking_settings (
    booking_settings_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    slot_interval_minutes INTEGER NOT NULL DEFAULT 15,

    minimum_booking_notice_hours INTEGER
        NOT NULL DEFAULT 24,

    maximum_booking_days_ahead INTEGER
        NOT NULL DEFAULT 90,

    default_buffer_before_minutes INTEGER
        NOT NULL DEFAULT 0,

    default_buffer_after_minutes INTEGER
        NOT NULL DEFAULT 0,

    allow_any_provider BOOLEAN NOT NULL DEFAULT TRUE,

    public_booking_enabled BOOLEAN NOT NULL DEFAULT FALSE,

    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_by INTEGER,
    updated_by INTEGER,

    CONSTRAINT fk_booking_settings_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_booking_settings_business_unit
        FOREIGN KEY (business_unit_id)
        REFERENCES business_units(business_unit_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_booking_settings_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_booking_settings_updated_by
        FOREIGN KEY (updated_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT uq_booking_settings_workspace
        UNIQUE (spa_id, business_unit_id),

    CONSTRAINT chk_booking_slot_interval
        CHECK (
            slot_interval_minutes BETWEEN 5 AND 120
            AND MOD(slot_interval_minutes, 5) = 0
        ),

    CONSTRAINT chk_booking_minimum_notice
        CHECK (
            minimum_booking_notice_hours
            BETWEEN 0 AND 8760
        ),

    CONSTRAINT chk_booking_days_ahead
        CHECK (
            maximum_booking_days_ahead
            BETWEEN 1 AND 730
        ),

    CONSTRAINT chk_booking_buffer_before
        CHECK (
            default_buffer_before_minutes
            BETWEEN 0 AND 240
        ),

    CONSTRAINT chk_booking_buffer_after
        CHECK (
            default_buffer_after_minutes
            BETWEEN 0 AND 240
        )
);


CREATE INDEX IF NOT EXISTS
idx_booking_settings_spa_workspace
ON booking_settings (
    spa_id,
    business_unit_id
);


-- Create safe disabled defaults for every existing workspace.

INSERT INTO booking_settings (
    spa_id,
    business_unit_id,
    slot_interval_minutes,
    minimum_booking_notice_hours,
    maximum_booking_days_ahead,
    default_buffer_before_minutes,
    default_buffer_after_minutes,
    allow_any_provider,
    public_booking_enabled
)
SELECT
    bu.spa_id,
    bu.business_unit_id,
    15,
    24,
    90,
    0,
    0,
    TRUE,
    FALSE
FROM business_units bu
WHERE bu.is_active = TRUE
ON CONFLICT (
    spa_id,
    business_unit_id
)
DO NOTHING;


-- =========================================================
-- 2. BUSINESS BOOKING HOURS
-- day_of_week:
-- 0 = Sunday
-- 1 = Monday
-- 2 = Tuesday
-- 3 = Wednesday
-- 4 = Thursday
-- 5 = Friday
-- 6 = Saturday
--
-- Multiple rows per day allow split schedules such as:
-- 9:00 AM–12:00 PM and 1:00 PM–5:00 PM.
-- Overnight periods are not supported in v1.
-- =========================================================

CREATE TABLE IF NOT EXISTS booking_business_hours (
    booking_business_hour_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    day_of_week SMALLINT NOT NULL,

    start_time TIME WITHOUT TIME ZONE NOT NULL,
    end_time TIME WITHOUT TIME ZONE NOT NULL,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_by INTEGER,
    updated_by INTEGER,

    CONSTRAINT fk_booking_business_hours_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_booking_business_hours_unit
        FOREIGN KEY (business_unit_id)
        REFERENCES business_units(business_unit_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_booking_business_hours_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_booking_business_hours_updated_by
        FOREIGN KEY (updated_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT uq_booking_business_hours_period
        UNIQUE (
            spa_id,
            business_unit_id,
            day_of_week,
            start_time,
            end_time
        ),

    CONSTRAINT chk_booking_business_day
        CHECK (
            day_of_week BETWEEN 0 AND 6
        ),

    CONSTRAINT chk_booking_business_time_range
        CHECK (
            start_time < end_time
        )
);


CREATE INDEX IF NOT EXISTS
idx_booking_business_hours_lookup
ON booking_business_hours (
    spa_id,
    business_unit_id,
    day_of_week,
    is_active
);


-- =========================================================
-- 3. PROVIDER BOOKING HOURS
-- Provider hours are later validated by the application
-- to ensure they fall within business operating hours.
-- =========================================================

CREATE TABLE IF NOT EXISTS provider_booking_hours (
    provider_booking_hour_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    provider_employee_id INTEGER NOT NULL,

    day_of_week SMALLINT NOT NULL,

    start_time TIME WITHOUT TIME ZONE NOT NULL,
    end_time TIME WITHOUT TIME ZONE NOT NULL,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_by INTEGER,
    updated_by INTEGER,

    CONSTRAINT fk_provider_booking_hours_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_provider_booking_hours_unit
        FOREIGN KEY (business_unit_id)
        REFERENCES business_units(business_unit_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_provider_booking_hours_employee
        FOREIGN KEY (provider_employee_id)
        REFERENCES employees(employee_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_provider_booking_hours_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_provider_booking_hours_updated_by
        FOREIGN KEY (updated_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT uq_provider_booking_hours_period
        UNIQUE (
            spa_id,
            business_unit_id,
            provider_employee_id,
            day_of_week,
            start_time,
            end_time
        ),

    CONSTRAINT chk_provider_booking_day
        CHECK (
            day_of_week BETWEEN 0 AND 6
        ),

    CONSTRAINT chk_provider_booking_time_range
        CHECK (
            start_time < end_time
        )
);


CREATE INDEX IF NOT EXISTS
idx_provider_booking_hours_lookup
ON provider_booking_hours (
    spa_id,
    business_unit_id,
    provider_employee_id,
    day_of_week,
    is_active
);


-- =========================================================
-- 4. PROVIDER SERVICE ASSIGNMENTS
-- A provider becomes publicly bookable by being assigned
-- one or more active services.
--
-- Overrides are optional. When NULL, Peach Suite Pro uses
-- the values from service_name_types.
-- =========================================================

CREATE TABLE IF NOT EXISTS provider_service_types (
    provider_service_type_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    provider_employee_id INTEGER NOT NULL,
    service_type_id INTEGER NOT NULL,

    duration_override_minutes INTEGER,
    price_override NUMERIC(10, 2),

    buffer_before_minutes INTEGER,
    buffer_after_minutes INTEGER,

    is_publicly_bookable BOOLEAN NOT NULL DEFAULT TRUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_by INTEGER,
    updated_by INTEGER,

    CONSTRAINT fk_provider_service_types_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_provider_service_types_unit
        FOREIGN KEY (business_unit_id)
        REFERENCES business_units(business_unit_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_provider_service_types_employee
        FOREIGN KEY (provider_employee_id)
        REFERENCES employees(employee_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_provider_service_types_service
        FOREIGN KEY (service_type_id)
        REFERENCES service_name_types(service_type_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_provider_service_types_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_provider_service_types_updated_by
        FOREIGN KEY (updated_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT uq_provider_service_assignment
        UNIQUE (
            spa_id,
            business_unit_id,
            provider_employee_id,
            service_type_id
        ),

    CONSTRAINT chk_provider_service_duration
        CHECK (
            duration_override_minutes IS NULL
            OR duration_override_minutes > 0
        ),

    CONSTRAINT chk_provider_service_price
        CHECK (
            price_override IS NULL
            OR price_override >= 0
        ),

    CONSTRAINT chk_provider_service_buffer_before
        CHECK (
            buffer_before_minutes IS NULL
            OR buffer_before_minutes BETWEEN 0 AND 240
        ),

    CONSTRAINT chk_provider_service_buffer_after
        CHECK (
            buffer_after_minutes IS NULL
            OR buffer_after_minutes BETWEEN 0 AND 240
        )
);


CREATE INDEX IF NOT EXISTS
idx_provider_service_types_provider
ON provider_service_types (
    spa_id,
    business_unit_id,
    provider_employee_id,
    is_active
);


CREATE INDEX IF NOT EXISTS
idx_provider_service_types_service
ON provider_service_types (
    spa_id,
    business_unit_id,
    service_type_id,
    is_active
);


-- =========================================================
-- 5. PROVIDER TIME OFF / BLOCKED TIME
--
-- Timestamps are stored as local business time, consistent
-- with the existing appointment date and time design.
-- =========================================================

CREATE TABLE IF NOT EXISTS provider_time_off (
    provider_time_off_id SERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    provider_employee_id INTEGER NOT NULL,

    starts_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    ends_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,

    block_type VARCHAR(30)
        NOT NULL DEFAULT 'time_off',

    reason VARCHAR(255),

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP WITHOUT TIME ZONE
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_by INTEGER,
    updated_by INTEGER,

    CONSTRAINT fk_provider_time_off_spa
        FOREIGN KEY (spa_id)
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_provider_time_off_unit
        FOREIGN KEY (business_unit_id)
        REFERENCES business_units(business_unit_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_provider_time_off_employee
        FOREIGN KEY (provider_employee_id)
        REFERENCES employees(employee_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_provider_time_off_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_provider_time_off_updated_by
        FOREIGN KEY (updated_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT chk_provider_time_off_range
        CHECK (
            starts_at < ends_at
        ),

    CONSTRAINT chk_provider_time_off_type
        CHECK (
            block_type IN (
                'time_off',
                'vacation',
                'meeting',
                'personal',
                'blocked'
            )
        )
);


CREATE INDEX IF NOT EXISTS
idx_provider_time_off_lookup
ON provider_time_off (
    spa_id,
    business_unit_id,
    provider_employee_id,
    starts_at,
    ends_at
)
WHERE is_active = TRUE;


COMMIT;
