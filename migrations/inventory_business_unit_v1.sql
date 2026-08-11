BEGIN;

-- =========================================================
-- Inventory — Enterprise workspace ownership
--
-- Adds business_unit_id to inventory products and movements.
-- Historical rows are assigned only when the owning spa has
-- exactly one active workspace. Never guess when multiple
-- active workspaces exist.
-- =========================================================


-- =========================================================
-- 1. Add nullable workspace ownership
-- =========================================================

ALTER TABLE inventory_products
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;

ALTER TABLE inventory_movements
ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


-- =========================================================
-- 2. Backfill inventory products
-- =========================================================

UPDATE inventory_products p
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = p.spa_id
      AND bu.is_active = TRUE
    HAVING COUNT(*) = 1
)
WHERE p.business_unit_id IS NULL;


-- =========================================================
-- 3. Backfill movements from their parent product
-- =========================================================

UPDATE inventory_movements m
SET business_unit_id = p.business_unit_id
FROM inventory_products p
WHERE m.business_unit_id IS NULL
  AND m.product_id = p.product_id
  AND m.spa_id = p.spa_id
  AND p.business_unit_id IS NOT NULL;


-- =========================================================
-- 4. Validate ownership before enforcing constraints
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM inventory_products
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'inventory_products contains rows without business_unit_id';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM inventory_movements
        WHERE business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'inventory_movements contains rows without business_unit_id';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM inventory_products p
        LEFT JOIN business_units bu
          ON bu.business_unit_id = p.business_unit_id
         AND bu.spa_id = p.spa_id
        WHERE bu.business_unit_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'inventory_products contains invalid spa/workspace assignments';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM inventory_movements m
        JOIN inventory_products p
          ON p.product_id = m.product_id
        WHERE m.spa_id <> p.spa_id
           OR m.business_unit_id <> p.business_unit_id
    ) THEN
        RAISE EXCEPTION
            'inventory_movements contains product workspace mismatches';
    END IF;
END
$$;


-- =========================================================
-- 5. Require workspace ownership
-- =========================================================

ALTER TABLE inventory_products
ALTER COLUMN business_unit_id SET NOT NULL;

ALTER TABLE inventory_movements
ALTER COLUMN business_unit_id SET NOT NULL;


-- =========================================================
-- 6. Tenant-safe workspace foreign keys
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_inventory_products_business_unit_spa'
    ) THEN
        ALTER TABLE inventory_products
        ADD CONSTRAINT
            fk_inventory_products_business_unit_spa
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        );
    END IF;
END
$$;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_inventory_movements_business_unit_spa'
    ) THEN
        ALTER TABLE inventory_movements
        ADD CONSTRAINT
            fk_inventory_movements_business_unit_spa
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        );
    END IF;
END
$$;


-- =========================================================
-- 7. Make product identity workspace-safe
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'uq_inventory_products_workspace_identity'
    ) THEN
        ALTER TABLE inventory_products
        ADD CONSTRAINT
            uq_inventory_products_workspace_identity
        UNIQUE (
            product_id,
            spa_id,
            business_unit_id
        );
    END IF;
END
$$;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'fk_inventory_movements_workspace_product'
    ) THEN
        ALTER TABLE inventory_movements
        ADD CONSTRAINT
            fk_inventory_movements_workspace_product
        FOREIGN KEY (
            product_id,
            spa_id,
            business_unit_id
        )
        REFERENCES inventory_products (
            product_id,
            spa_id,
            business_unit_id
        )
        ON DELETE CASCADE;
    END IF;
END
$$;


-- =========================================================
-- 8. Change SKU uniqueness from spa-wide to workspace-wide
-- =========================================================

ALTER TABLE inventory_products
DROP CONSTRAINT IF EXISTS unique_inventory_sku_per_spa;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'unique_inventory_sku_per_workspace'
    ) THEN
        ALTER TABLE inventory_products
        ADD CONSTRAINT
            unique_inventory_sku_per_workspace
        UNIQUE (
            spa_id,
            business_unit_id,
            sku
        );
    END IF;
END
$$;


-- =========================================================
-- 9. Workspace indexes
-- =========================================================

CREATE INDEX IF NOT EXISTS
idx_inventory_products_workspace_active
ON inventory_products (
    spa_id,
    business_unit_id,
    active,
    product_name
);

CREATE INDEX IF NOT EXISTS
idx_inventory_movements_workspace_product_date
ON inventory_movements (
    spa_id,
    business_unit_id,
    product_id,
    movement_date DESC,
    movement_id DESC
);

COMMIT;
