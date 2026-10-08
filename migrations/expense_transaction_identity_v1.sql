BEGIN;

-- Peach Suite Pro: Permanent Expense Transaction Identity
-- Additive migration. Existing Expense records remain unchanged.

ALTER TABLE expenses
    ADD COLUMN transaction_source VARCHAR(255),
    ADD COLUMN external_transaction_id VARCHAR(255);

-- An external ID must have an identifiable source.
ALTER TABLE expenses
    ADD CONSTRAINT chk_expenses_external_id_source
    CHECK (
        NULLIF(BTRIM(external_transaction_id), '') IS NULL
        OR NULLIF(BTRIM(transaction_source), '') IS NOT NULL
    );

-- Prevent repeated external transactions within a workspace.
CREATE UNIQUE INDEX uq_expenses_workspace_external_identity
ON expenses (
    spa_id,
    business_unit_id,
    LOWER(REGEXP_REPLACE(
        BTRIM(transaction_source),
        '[[:space:]]+', ' ', 'g'
    )),
    BTRIM(external_transaction_id)
)
WHERE NULLIF(BTRIM(transaction_source), '') IS NOT NULL
  AND NULLIF(BTRIM(external_transaction_id), '') IS NOT NULL;

COMMENT ON COLUMN expenses.transaction_source IS
    'Original external account or system identifying an expense transaction.';

COMMENT ON COLUMN expenses.external_transaction_id IS
    'Source-issued transaction identifier used for duplicate prevention.';

COMMIT;
