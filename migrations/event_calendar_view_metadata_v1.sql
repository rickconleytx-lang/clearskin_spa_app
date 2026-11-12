-- EC-065 View Events reference metadata, NOT event scheduling data.
-- ADDITIVE LOCAL migration only. Review/back up before applying separately.
-- Does not modify event_calendar_events, business_schedule or calendar routes.
CREATE TABLE IF NOT EXISTS event_calendar_view_metadata (
    event_id BIGINT PRIMARY KEY
        REFERENCES event_calendar_events(event_id) ON DELETE CASCADE,
    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    next_date_reference VARCHAR(120) NOT NULL DEFAULT '',
    archived_at TIMESTAMPTZ NULL,
    archived_by_user_id INTEGER NULL REFERENCES users(user_id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ec_view_metadata_archiver_check
      CHECK (archived_by_user_id IS NULL OR archived_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ec_view_metadata_scope_archive_idx
  ON event_calendar_view_metadata (spa_id, business_unit_id, archived_at);
