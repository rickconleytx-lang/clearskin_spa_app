BEGIN;

-- Client Status names belong to an individual business.
-- Remove the obsolete global uniqueness rule while preserving
-- the existing UNIQUE (spa_id, status_name) constraint.
ALTER TABLE client_statuses
DROP CONSTRAINT IF EXISTS client_statuses_status_name_key;

-- Also enforce tenant uniqueness without regard to capitalization
-- or accidental leading/trailing spaces.
CREATE UNIQUE INDEX IF NOT EXISTS
    unique_client_status_name_per_spa_ci
ON client_statuses (
    spa_id,
    LOWER(BTRIM(status_name))
);

-- Give every existing business the standard Client Status options.
-- Existing tenant-owned options are preserved.
INSERT INTO client_statuses (
    spa_id,
    status_name,
    is_active
)
SELECT
    s.spa_id,
    defaults.status_name,
    TRUE
FROM spas AS s
CROSS JOIN (
    VALUES
        ('Current'),
        ('Previous'),
        ('Prior Client'),
        ('Inactive'),
        ('Event Contact')
) AS defaults(status_name)
WHERE NOT EXISTS (
    SELECT 1
    FROM client_statuses AS existing
    WHERE existing.spa_id = s.spa_id
      AND LOWER(BTRIM(existing.status_name))
          = LOWER(BTRIM(defaults.status_name))
);

COMMIT;
