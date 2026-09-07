-- Peach Suite Pro
-- Verification support script extracted 2026-09-07
-- Original migration: migrations/remove_legacy_square_booking_v1.sql
-- This file performs verification only; it is not a migration.

SELECT to_regclass('public.incoming_square_bookings') AS incoming_square_bookings;
