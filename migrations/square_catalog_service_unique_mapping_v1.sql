-- =========================================================
-- Square V2
-- One active Square Catalog mapping per PSP service
-- per Square connection / workspace / environment.
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM square_catalog_mappings
        WHERE is_active = TRUE
          AND mapping_type = 'service_type'
          AND service_type_id IS NOT NULL
        GROUP BY
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
            service_type_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Cannot create unique Square service mapping index: duplicate active service mappings exist.';
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_square_catalog_service_mapping_active
ON square_catalog_mappings (
    square_connection_id,
    spa_id,
    business_unit_id,
    environment,
    service_type_id
)
WHERE
    is_active = TRUE
    AND mapping_type = 'service_type'
    AND service_type_id IS NOT NULL;
