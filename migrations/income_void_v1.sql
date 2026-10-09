BEGIN;

-- Peach Suite Pro: Income Archive / Void V1
-- Additive only. Existing Income remains active.

ALTER TABLE income
    ADD COLUMN IF NOT EXISTS voided_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS voided_by_user_id INTEGER,
    ADD COLUMN IF NOT EXISTS void_reason TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.income'::regclass
          AND conname = 'chk_income_void_metadata_complete'
    ) THEN
        ALTER TABLE income
            ADD CONSTRAINT chk_income_void_metadata_complete
            CHECK (
                (
                    voided_at IS NULL
                    AND voided_by_user_id IS NULL
                    AND void_reason IS NULL
                )
                OR
                (
                    voided_at IS NOT NULL
                    AND voided_by_user_id IS NOT NULL
                    AND void_reason IS NOT NULL
                    AND length(btrim(void_reason)) >= 10
                )
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_income_active_workspace_date
    ON income (
        spa_id,
        business_unit_id,
        income_date DESC,
        income_id DESC
    )
    WHERE voided_at IS NULL;

COMMENT ON COLUMN income.voided_at IS
    'Timestamp when an Income record was archived/voided. '
    'NULL means active.';

COMMENT ON COLUMN income.voided_by_user_id IS
    'Authenticated PSP user who archived this Income record.';

COMMENT ON COLUMN income.void_reason IS
    'Required explanation for archiving or voiding Income.';

COMMIT;
