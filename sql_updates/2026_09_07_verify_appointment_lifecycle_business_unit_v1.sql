-- Peach Suite Pro
-- Verification support script extracted 2026-09-07
-- Original migration: migrations/appointment_lifecycle_business_unit_v1_finalize.sql
-- This file performs verification only; it is not a migration.

-- ==================================================


SELECT
    (SELECT COUNT(*) FROM appointment_wrap_up) AS wrap_up_rows,
    (SELECT COUNT(*) FROM appointment_history) AS history_rows,

    (SELECT is_nullable
     FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name = 'appointment_wrap_up'
       AND column_name = 'business_unit_id')
        AS wrap_up_nullable,

    (SELECT is_nullable
     FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name = 'appointment_history'
       AND column_name = 'business_unit_id')
        AS history_nullable,

    (SELECT COUNT(*)
     FROM appointment_wrap_up
     WHERE business_unit_id IS NULL)
        AS wrap_up_nulls,

    (SELECT COUNT(*)
     FROM appointment_history
     WHERE business_unit_id IS NULL)
        AS history_nulls,

    (SELECT COUNT(*)
     FROM appointment_wrap_up aw
     LEFT JOIN business_units bu
       ON bu.business_unit_id = aw.business_unit_id
      AND bu.spa_id = aw.spa_id
     WHERE bu.business_unit_id IS NULL)
        AS wrap_up_invalid,

    (SELECT COUNT(*)
     FROM appointment_history ah
     LEFT JOIN business_units bu
       ON bu.business_unit_id = ah.business_unit_id
      AND bu.spa_id = ah.spa_id
     WHERE bu.business_unit_id IS NULL)
        AS history_invalid,

    (SELECT COUNT(*)
     FROM appointment_wrap_up aw
     JOIN appointments a
       ON a.appointment_id = aw.appointment_id
     WHERE aw.spa_id <> a.spa_id
        OR aw.business_unit_id <> a.business_unit_id)
        AS wrap_up_mismatches,

    (SELECT COUNT(*)
     FROM appointment_history ah
     JOIN appointments a
       ON a.appointment_id = ah.appointment_id
     WHERE ah.spa_id <> a.spa_id
        OR ah.business_unit_id <> a.business_unit_id)
        AS history_mismatches,

    (SELECT COUNT(*)
     FROM pg_constraint
     WHERE conname IN (
         'uq_appointments_workspace_identity',
         'fk_appointments_business_unit_spa',
         'fk_appointment_wrap_up_business_unit_spa',
         'fk_appointment_wrap_up_appointment_workspace',
         'fk_appointment_history_business_unit_spa'
     ))
        AS expected_constraints;
