-- Peach Suite Pro
-- Verification support script extracted 2026-09-07
-- Original migration: migrations/square_v2_foundation_v1.sql
-- This file performs verification only; it is not a migration.

-- ==================================================


-- PRODUCTION SQUARE V2 FOUNDATION VERIFICATION

-- 1. Confirm all seven Square V2 tables exist and report current row counts.
SELECT
    t.table_name,
    CASE
        WHEN to_regclass('public.' || t.table_name) IS NOT NULL
            THEN 'EXISTS'
        ELSE 'MISSING'
    END AS table_status
FROM (
    VALUES
        ('square_connections'),
        ('square_locations'),
        ('square_webhook_events'),
        ('square_payments'),
        ('square_customer_mappings'),
        ('square_catalog_mappings'),
        ('square_payment_line_items')
) AS t(table_name)
ORDER BY t.table_name;


SELECT 'square_connections' AS table_name, COUNT(*) AS row_count FROM square_connections
UNION ALL
SELECT 'square_locations', COUNT(*) FROM square_locations
UNION ALL
SELECT 'square_webhook_events', COUNT(*) FROM square_webhook_events
UNION ALL
SELECT 'square_payments', COUNT(*) FROM square_payments
UNION ALL
SELECT 'square_customer_mappings', COUNT(*) FROM square_customer_mappings
UNION ALL
SELECT 'square_catalog_mappings', COUNT(*) FROM square_catalog_mappings
UNION ALL
SELECT 'square_payment_line_items', COUNT(*) FROM square_payment_line_items;


-- 2. Verify the new workspace identity / Income linkage constraints.
SELECT
    conrelid::regclass::text AS table_name,
    conname,
    pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conname IN (
    'uq_clients_workspace_identity',
    'uq_income_workspace_identity',
    'uq_inventory_movements_workspace_identity',
    'fk_inventory_movements_workspace_income'
)
ORDER BY conrelid::regclass::text, conname;


-- 3. Verify Square workspace-aware foreign keys.
SELECT
    conrelid::regclass::text AS child_table,
    conname,
    pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conname LIKE 'fk_square_%'
ORDER BY child_table, conname;


-- 4. Sanity check existing production data is still present.
SELECT
    (SELECT COUNT(*) FROM clients) AS clients,
    (SELECT COUNT(*) FROM appointments) AS appointments,
    (SELECT COUNT(*) FROM income) AS income,
    (SELECT COUNT(*) FROM inventory_products) AS inventory_products,
    (SELECT COUNT(*) FROM inventory_movements) AS inventory_movements;


-- ==================================================

-- FINAL PRODUCTION SQUARE V2 FOUNDATION PASS/FAIL

SELECT
    (SELECT COUNT(*) FROM square_connections) AS square_connections,
    (SELECT COUNT(*) FROM square_locations) AS square_locations,
    (SELECT COUNT(*) FROM square_webhook_events) AS square_webhook_events,
    (SELECT COUNT(*) FROM square_payments) AS square_payments,
    (SELECT COUNT(*) FROM square_customer_mappings) AS square_customer_mappings,
    (SELECT COUNT(*) FROM square_catalog_mappings) AS square_catalog_mappings,
    (SELECT COUNT(*) FROM square_payment_line_items) AS square_payment_line_items,
    (
        SELECT COUNT(*)
        FROM pg_constraint
        WHERE conname IN (
            'uq_clients_workspace_identity',
            'uq_income_workspace_identity',
            'uq_inventory_movements_workspace_identity',
            'fk_inventory_movements_workspace_income'
        )
    ) AS core_constraints,
    (
        SELECT COUNT(*)
        FROM pg_constraint
        WHERE conname LIKE 'fk_square_%'
    ) AS square_foreign_keys;
