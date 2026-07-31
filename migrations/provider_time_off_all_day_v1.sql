BEGIN;

ALTER TABLE provider_time_off
ADD COLUMN IF NOT EXISTS is_all_day
BOOLEAN NOT NULL DEFAULT FALSE;

-- Recognize existing midnight-to-midnight full-day records.
UPDATE provider_time_off
SET is_all_day = TRUE
WHERE is_all_day = FALSE
  AND starts_at::time = TIME '00:00:00'
  AND ends_at = starts_at + INTERVAL '1 day';

COMMIT;
