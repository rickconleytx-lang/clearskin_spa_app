-- Remove the remaining abandoned Square V1 schema remnants.
-- Square V2 will use new workspace-aware reconciliation and mapping tables.

BEGIN;

DO $$
DECLARE
    product_ref_count BIGINT := 0;
    appointment_square_count BIGINT := 0;
    visit_square_count BIGINT := 0;
BEGIN
    IF to_regclass('public.square_products_ref') IS NOT NULL THEN
        SELECT COUNT(*)
        INTO product_ref_count
        FROM square_products_ref;

        IF product_ref_count > 0 THEN
            RAISE EXCEPTION
                'Refusing to drop square_products_ref: % row(s) exist.',
                product_ref_count;
        END IF;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'appointments'
          AND column_name = 'square_appointment_id'
    ) THEN
        EXECUTE
            'SELECT COUNT(*) FROM appointments
             WHERE NULLIF(BTRIM(square_appointment_id), '''') IS NOT NULL'
        INTO appointment_square_count;

        IF appointment_square_count > 0 THEN
            RAISE EXCEPTION
                'Refusing to drop appointments.square_appointment_id: % populated row(s) exist.',
                appointment_square_count;
        END IF;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'visit_summary'
          AND column_name = 'square_payment_id'
    ) THEN
        EXECUTE
            'SELECT COUNT(*) FROM visit_summary
             WHERE NULLIF(BTRIM(square_payment_id), '''') IS NOT NULL'
        INTO visit_square_count;

        IF visit_square_count > 0 THEN
            RAISE EXCEPTION
                'Refusing to drop visit_summary.square_payment_id: % populated row(s) exist.',
                visit_square_count;
        END IF;
    END IF;
END $$;

DROP TABLE IF EXISTS square_products_ref;
ALTER TABLE appointments
    DROP COLUMN IF EXISTS square_appointment_id;
ALTER TABLE visit_summary
    DROP COLUMN IF EXISTS square_payment_id;

COMMIT;
