BEGIN;

ALTER TABLE income
    ADD COLUMN IF NOT EXISTS pos_amount
        NUMERIC(10, 2)
        NOT NULL
        DEFAULT 0.00;

COMMENT ON COLUMN income.pos_amount IS
    'Pre-tax, pre-tip sales amount recorded through PeachPOS / POS Daily Sales mode.';

COMMIT;
