-- Peach Suite Pro
-- Remove abandoned Square booking-import prototype.
-- Square V2 will be rebuilt as a workspace-aware commerce
-- and reconciliation integration.
--
-- Safety: refuse to drop the table if it contains any rows.

BEGIN;

DO $$
DECLARE
    legacy_row_count BIGINT;
BEGIN
    IF to_regclass('public.incoming_square_bookings') IS NOT NULL THEN
        SELECT COUNT(*)
        INTO legacy_row_count
        FROM incoming_square_bookings;

        IF legacy_row_count > 0 THEN
            RAISE EXCEPTION
                'Refusing to drop incoming_square_bookings: % row(s) exist.',
                legacy_row_count;
        END IF;
    END IF;
END
$$;

DROP TABLE IF EXISTS incoming_square_bookings;

COMMIT;
