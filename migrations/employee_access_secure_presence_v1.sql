-- ============================================================
-- Peach Suite Pro
-- Employee Access Secure Presence V1
--
-- Adds a security-only marker to the existing browser tab
-- presence records. This allows Employee Access verification
-- to remain active across protected pages and expire after the
-- 15-second protected-area grace period without modifying the
-- Flask session during page unload/navigation.
-- ============================================================

ALTER TABLE browser_session_tabs
    ADD COLUMN IF NOT EXISTS employee_access_secure
        BOOLEAN NOT NULL DEFAULT FALSE;


CREATE INDEX IF NOT EXISTS
    idx_browser_session_tabs_employee_access_secure
ON browser_session_tabs (
    session_marker_hash,
    user_id,
    spa_id,
    business_unit_id,
    employee_access_secure,
    last_seen_at DESC
)
WHERE employee_access_secure = TRUE;
