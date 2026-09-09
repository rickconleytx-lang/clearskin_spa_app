BEGIN;

ALTER TABLE automatic_expenses
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP WITHOUT TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_automatic_expenses_workspace_archive
    ON automatic_expenses (
        spa_id,
        business_unit_id,
        archived_at
    );

COMMIT;
