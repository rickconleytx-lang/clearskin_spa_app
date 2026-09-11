-- Peach Suite Pro
-- Explicit PSP business-user to employee identity link
-- V1

BEGIN;

ALTER TABLE business_unit_memberships
    ADD COLUMN IF NOT EXISTS employee_id INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_business_unit_membership_employee'
          AND conrelid = 'business_unit_memberships'::regclass
    ) THEN
        ALTER TABLE business_unit_memberships
            ADD CONSTRAINT fk_business_unit_membership_employee
            FOREIGN KEY (
                spa_id,
                business_unit_id,
                employee_id
            )
            REFERENCES employee_business_unit_memberships (
                spa_id,
                business_unit_id,
                employee_id
            )
            ON DELETE RESTRICT;
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_business_unit_active_employee_link
ON business_unit_memberships (
    spa_id,
    business_unit_id,
    employee_id
)
WHERE is_active = TRUE
  AND employee_id IS NOT NULL;

COMMIT;
