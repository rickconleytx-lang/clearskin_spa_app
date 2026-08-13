-- =========================================================
-- Square V2
-- One active Square Catalog mapping per PSP inventory product
-- per Square connection / workspace / environment.
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM square_catalog_mappings
        WHERE is_active = TRUE
          AND mapping_type = 'inventory_product'
          AND inventory_product_id IS NOT NULL
        GROUP BY
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
            inventory_product_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Cannot create unique Square inventory mapping index: duplicate active inventory mappings exist.';
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_square_catalog_inventory_mapping_active
ON square_catalog_mappings (
    square_connection_id,
    spa_id,
    business_unit_id,
    environment,
    inventory_product_id
)
WHERE
    is_active = TRUE
    AND mapping_type = 'inventory_product'
    AND inventory_product_id IS NOT NULL;
