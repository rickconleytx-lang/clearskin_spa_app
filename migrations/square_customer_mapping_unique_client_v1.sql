-- =========================================================
-- Square V2
-- One active Square customer mapping per PSP client
--
-- A PSP client may retain inactive historical mappings,
-- but within one Square connection/workspace it may have
-- at most one active Square customer identity.
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM square_customer_mappings
        WHERE is_active = TRUE
        GROUP BY
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
            client_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Duplicate active Square customer mappings exist; migration stopped.';
    END IF;
END
$$;


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_square_customer_mapping_client_active
ON square_customer_mappings (
    square_connection_id,
    spa_id,
    business_unit_id,
    environment,
    client_id
)
WHERE is_active = TRUE;
