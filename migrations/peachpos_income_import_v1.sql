BEGIN;

-- =========================================================
-- PEACHPOS INCOME IMPORT V1
--
-- Adds:
--   • workspace ownership foundation for credit processors
--   • processor Merchant ID / Account ID safety identity
--   • processor-supplied transaction timestamp
--   • optional Event Name
--   • processor transaction status
--   • 8 immutable processor-specific data fields
--   • processor/workspace-specific display labels
--   • Import Records review decision
--
-- Database/internal field names remain immutable.
-- User-facing processor field labels are customizable.
-- =========================================================


-- ---------------------------------------------------------
-- 1. CREDIT PROCESSOR WORKSPACE FOUNDATION
-- ---------------------------------------------------------

ALTER TABLE credit_processors
    ADD COLUMN IF NOT EXISTS business_unit_id INTEGER,
    ADD COLUMN IF NOT EXISTS merchant_account_identifier TEXT;


-- Backfill a processor when its existing Income history
-- proves that it belongs to exactly one workspace.
UPDATE credit_processors cp
SET business_unit_id = inferred.business_unit_id
FROM (
    SELECT
        cp2.credit_processor_id,
        MIN(i.business_unit_id) AS business_unit_id
    FROM credit_processors cp2
    JOIN income i
      ON i.credit_processor_id = cp2.credit_processor_id
     AND i.spa_id = cp2.spa_id
    GROUP BY cp2.credit_processor_id
    HAVING COUNT(DISTINCT i.business_unit_id) = 1
) inferred
WHERE cp.credit_processor_id = inferred.credit_processor_id
  AND cp.business_unit_id IS NULL;


-- If a business has exactly one workspace, safely assign any
-- still-unassigned legacy processor to that workspace.
UPDATE credit_processors cp
SET business_unit_id = only_unit.business_unit_id
FROM (
    SELECT
        spa_id,
        MIN(business_unit_id) AS business_unit_id
    FROM business_units
    GROUP BY spa_id
    HAVING COUNT(*) = 1
) only_unit
WHERE cp.spa_id = only_unit.spa_id
  AND cp.business_unit_id IS NULL;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_credit_processors_workspace'
    ) THEN
        ALTER TABLE credit_processors
            ADD CONSTRAINT fk_credit_processors_workspace
            FOREIGN KEY (business_unit_id, spa_id)
            REFERENCES business_units (
                business_unit_id,
                spa_id
            )
            ON DELETE CASCADE;
    END IF;
END
$$;


CREATE INDEX IF NOT EXISTS
    idx_credit_processors_workspace
ON credit_processors (
    spa_id,
    business_unit_id,
    is_active
);


-- Required for a workspace-safe composite foreign key from
-- the processor-field label table below.
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_credit_processors_workspace_identity
ON credit_processors (
    credit_processor_id,
    spa_id,
    business_unit_id
);


-- A workspace should not accidentally create duplicate processor
-- names that differ only by capitalization or surrounding spaces.
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_credit_processors_workspace_name_ci
ON credit_processors (
    spa_id,
    business_unit_id,
    LOWER(BTRIM(credit_processor_name))
)
WHERE business_unit_id IS NOT NULL;


COMMENT ON COLUMN credit_processors.business_unit_id IS
    'Provider Workspace that owns this processor. Legacy rows may remain NULL only when ownership cannot be inferred safely.';

COMMENT ON COLUMN credit_processors.merchant_account_identifier IS
    'Merchant ID / Account ID configured for this processor account and used to verify PeachPOS import files belong to the expected merchant.';


-- ---------------------------------------------------------
-- 2. GENERIC PEACHPOS INCOME SOURCE DATA
-- ---------------------------------------------------------

ALTER TABLE income
    ADD COLUMN IF NOT EXISTS transaction_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS event_name VARCHAR(200),
    ADD COLUMN IF NOT EXISTS processor_status VARCHAR(100),
    ADD COLUMN IF NOT EXISTS processor_field_1 TEXT,
    ADD COLUMN IF NOT EXISTS processor_field_2 TEXT,
    ADD COLUMN IF NOT EXISTS processor_field_3 TEXT,
    ADD COLUMN IF NOT EXISTS processor_field_4 TEXT,
    ADD COLUMN IF NOT EXISTS processor_field_5 TEXT,
    ADD COLUMN IF NOT EXISTS processor_field_6 TEXT,
    ADD COLUMN IF NOT EXISTS processor_field_7 TEXT,
    ADD COLUMN IF NOT EXISTS processor_field_8 TEXT,
    ADD COLUMN IF NOT EXISTS processor_import_data JSONB;


COMMENT ON COLUMN income.transaction_at IS
    'Actual transaction timestamp supplied by the payment processor/source. income.created_at remains the PSP record creation/import timestamp.';

COMMENT ON COLUMN income.event_name IS
    'Optional business event name associated with the PeachPOS sale/import batch.';

COMMENT ON COLUMN income.processor_status IS
    'Transaction status supplied by the payment processor/source, separate from PSP import review status.';

COMMENT ON COLUMN income.processor_field_1 IS
    'Immutable PeachPOS processor custom field 1; user-facing label is configurable.';

COMMENT ON COLUMN income.processor_field_2 IS
    'Immutable PeachPOS processor custom field 2; user-facing label is configurable.';

COMMENT ON COLUMN income.processor_field_3 IS
    'Immutable PeachPOS processor custom field 3; user-facing label is configurable.';

COMMENT ON COLUMN income.processor_field_4 IS
    'Immutable PeachPOS processor custom field 4; user-facing label is configurable.';

COMMENT ON COLUMN income.processor_field_5 IS
    'Immutable PeachPOS processor custom field 5; user-facing label is configurable.';

COMMENT ON COLUMN income.processor_field_6 IS
    'Immutable PeachPOS processor custom field 6; user-facing label is configurable.';

COMMENT ON COLUMN income.processor_field_7 IS
    'Immutable PeachPOS processor custom field 7; user-facing label is configurable.';

COMMENT ON COLUMN income.processor_field_8 IS
    'Immutable PeachPOS processor custom field 8; user-facing label is configurable.';

COMMENT ON COLUMN income.processor_import_data IS
    'PeachPOS import metadata preserving which optional processor values were actually supplied by the source; accounting columns may use zero for legacy non-null storage compatibility.';


CREATE INDEX IF NOT EXISTS
    idx_income_peachpos_transaction_at
ON income (
    spa_id,
    business_unit_id,
    transaction_at
)
WHERE income_type = 'PeachPOS';


-- A processor transaction may be posted only once within
-- the same Provider Workspace and selected processor.
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_income_peachpos_processor_transaction
ON income (
    spa_id,
    business_unit_id,
    credit_processor_id,
    processor_payment_id
)
WHERE income_type = 'PeachPOS'
  AND credit_processor_id IS NOT NULL
  AND processor_payment_id IS NOT NULL
  AND BTRIM(processor_payment_id) <> '';


-- ---------------------------------------------------------
-- 3. PROCESSOR-SPECIFIC USER-FACING FIELD LABELS
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS peachpos_processor_field_labels (
    peachpos_processor_field_label_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    credit_processor_id INTEGER NOT NULL,

    field_key VARCHAR(50) NOT NULL,
    custom_label VARCHAR(100) NOT NULL,

    updated_by INTEGER NULL,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_peachpos_processor_labels_workspace
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_peachpos_processor_labels_processor
        FOREIGN KEY (
            credit_processor_id,
            spa_id,
            business_unit_id
        )
        REFERENCES credit_processors (
            credit_processor_id,
            spa_id,
            business_unit_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_peachpos_processor_labels_updated_by
        FOREIGN KEY (updated_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT chk_peachpos_processor_labels_field_key
        CHECK (
            field_key IN (
                'processor_field_1',
                'processor_field_2',
                'processor_field_3',
                'processor_field_4',
                'processor_field_5',
                'processor_field_6',
                'processor_field_7',
                'processor_field_8',
            )
        ),

    CONSTRAINT chk_peachpos_processor_labels_custom_label
        CHECK (
            BTRIM(custom_label) <> ''
        ),

    CONSTRAINT uq_peachpos_processor_field_label
        UNIQUE (
            spa_id,
            business_unit_id,
            credit_processor_id,
            field_key
        )
);


CREATE INDEX IF NOT EXISTS
    idx_peachpos_processor_field_labels_lookup
ON peachpos_processor_field_labels (
    spa_id,
    business_unit_id,
    credit_processor_id
);


COMMENT ON TABLE peachpos_processor_field_labels IS
    'User-facing labels for the 8 immutable PeachPOS processor fields, scoped to a processor and Provider Workspace.';

COMMENT ON COLUMN peachpos_processor_field_labels.field_key IS
    'Immutable backend key processor_field_1 through processor_field_8.';

COMMENT ON COLUMN peachpos_processor_field_labels.custom_label IS
    'User-facing field name used in PeachPOS screens and import mapping.';


-- ---------------------------------------------------------
-- 4. IMPORT REVIEW DECISION
-- ---------------------------------------------------------

ALTER TABLE import_run_rows
    ADD COLUMN IF NOT EXISTS review_decision VARCHAR(30);


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_import_run_rows_review_decision'
    ) THEN
        ALTER TABLE import_run_rows
            ADD CONSTRAINT chk_import_run_rows_review_decision
            CHECK (
                review_decision IS NULL
                OR review_decision IN (
                    'approved',
                    'needs_review',
                    'hold',
                    'discard'
                )
            );
    END IF;
END
$$;


CREATE INDEX IF NOT EXISTS
    idx_import_run_rows_review_decision
ON import_run_rows (
    import_run_id,
    review_decision
);


COMMENT ON COLUMN import_run_rows.review_decision IS
    'User-facing pre-post decision for import review: approved, needs_review, hold, or discard. NULL for import types that do not use row review decisions.';


COMMIT;
