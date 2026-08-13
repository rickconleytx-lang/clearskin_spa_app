-- =========================================================
-- Peach Suite Pro
-- Square V2 Foundation
--
-- Purpose:
--   Build a clean, workspace-aware Square integration layer
--   between Square and the existing PSP Income / Inventory
--   close-out workflow.
--
-- This migration DOES NOT:
--   - connect to Square
--   - create webhook routes
--   - alter existing Income behavior
--   - alter existing Inventory behavior
--   - import or reconcile any transaction
--
-- Flow target:
--   Finish Session
--       -> Add Income
--       -> Retrieve Square Data (when applicable)
--       -> Review / Save Income
--       -> Session Notes
--
-- Square records are staged first. Nothing may reach Income,
-- Appointments, Clients, or Inventory until the Square account
-- and location resolve to the correct spa + business_unit.
-- =========================================================

BEGIN;


-- =========================================================
-- EXISTING PSP WORKSPACE IDENTITIES
--
-- These redundant composite identities do not change the
-- existing global primary-key behavior. They allow Square
-- foreign keys to enforce that linked records belong to the
-- same spa + business_unit at the database level.
-- =========================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_clients_workspace_identity'
    ) THEN
        ALTER TABLE clients
        ADD CONSTRAINT uq_clients_workspace_identity
        UNIQUE (
            client_id,
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
        WHERE conname = 'uq_income_workspace_identity'
    ) THEN
        ALTER TABLE income
        ADD CONSTRAINT uq_income_workspace_identity
        UNIQUE (
            income_id,
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
        WHERE conname = 'uq_inventory_movements_workspace_identity'
    ) THEN
        ALTER TABLE inventory_movements
        ADD CONSTRAINT uq_inventory_movements_workspace_identity
        UNIQUE (
            movement_id,
            spa_id,
            business_unit_id
        );
    END IF;
END
$$;


-- Formalize the existing inventory_movements.income_id link.
-- Only income_id is nulled if an Income row is deleted; the
-- movement keeps its workspace identity and inventory history.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_inventory_movements_workspace_income'
    ) THEN
        ALTER TABLE inventory_movements
        ADD CONSTRAINT fk_inventory_movements_workspace_income
        FOREIGN KEY (
            income_id,
            spa_id,
            business_unit_id
        )
        REFERENCES income (
            income_id,
            spa_id,
            business_unit_id
        )
        ON DELETE SET NULL (income_id);
    END IF;
END
$$;



-- =========================================================
-- SQUARE CONNECTIONS
--
-- One Square seller authorization per PSP workspace and
-- environment. OAuth token columns are intentionally named
-- "ciphertext" so plaintext tokens are never treated as an
-- acceptable storage format.
-- =========================================================

CREATE TABLE IF NOT EXISTS square_connections (
    square_connection_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    environment VARCHAR(20) NOT NULL DEFAULT 'sandbox',
    merchant_id VARCHAR(255),

    connection_status VARCHAR(40)
        NOT NULL DEFAULT 'disconnected',

    oauth_access_token_ciphertext TEXT,
    oauth_refresh_token_ciphertext TEXT,
    oauth_token_expires_at TIMESTAMPTZ,
    oauth_scopes TEXT,

    connected_at TIMESTAMPTZ,
    last_sync_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_square_connections_environment
        CHECK (environment IN ('sandbox', 'production')),

    CONSTRAINT chk_square_connections_status
        CHECK (
            connection_status IN (
                'disconnected',
                'connected',
                'reauthorization_required',
                'disabled',
                'error'
            )
        ),

    CONSTRAINT fk_square_connections_workspace
        FOREIGN KEY (business_unit_id, spa_id)
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE,

    CONSTRAINT uq_square_connection_workspace_environment
        UNIQUE (
            spa_id,
            business_unit_id,
            environment
        ),

    CONSTRAINT uq_square_connection_workspace_identity
        UNIQUE (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        )
);


CREATE INDEX IF NOT EXISTS
    idx_square_connections_merchant
ON square_connections (
    environment,
    merchant_id
)
WHERE merchant_id IS NOT NULL;


-- =========================================================
-- SQUARE LOCATION MAPPINGS
--
-- A Square location must resolve to exactly one PSP workspace
-- within a Square environment before financial data can be
-- reconciled.
-- =========================================================

CREATE TABLE IF NOT EXISTS square_locations (
    square_location_mapping_id BIGSERIAL PRIMARY KEY,

    square_connection_id BIGINT NOT NULL,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    environment VARCHAR(20) NOT NULL,

    square_location_id VARCHAR(255) NOT NULL,
    location_name VARCHAR(255),

    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_square_locations_environment
        CHECK (environment IN ('sandbox', 'production')),

    CONSTRAINT fk_square_locations_connection_workspace
        FOREIGN KEY (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        )
        REFERENCES square_connections (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_locations_workspace
        FOREIGN KEY (business_unit_id, spa_id)
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE,

    CONSTRAINT uq_square_location_environment
        UNIQUE (
            environment,
            square_location_id
        )
);


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_square_location_default_per_connection
ON square_locations (
    square_connection_id
)
WHERE is_default = TRUE
  AND is_active = TRUE;


CREATE INDEX IF NOT EXISTS
    idx_square_locations_workspace
ON square_locations (
    spa_id,
    business_unit_id,
    is_active
);


-- =========================================================
-- SQUARE WEBHOOK EVENT LOG
--
-- Workspace fields remain nullable because an authentic event
-- may arrive before PSP can route the Square merchant/location.
-- Such events remain unrouted instead of being assigned to a
-- default spa or workspace.
-- =========================================================

CREATE TABLE IF NOT EXISTS square_webhook_events (
    square_webhook_event_id BIGSERIAL PRIMARY KEY,

    environment VARCHAR(20) NOT NULL,
    square_event_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(255) NOT NULL,

    merchant_id VARCHAR(255),
    square_location_id VARCHAR(255),
    square_payment_id VARCHAR(255),
    square_order_id VARCHAR(255),

    square_connection_id BIGINT,
    spa_id INTEGER,
    business_unit_id INTEGER,

    signature_valid BOOLEAN NOT NULL DEFAULT FALSE,

    routing_status VARCHAR(30)
        NOT NULL DEFAULT 'unrouted',

    processing_status VARCHAR(30)
        NOT NULL DEFAULT 'received',

    payload JSONB NOT NULL,

    processing_attempts INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,

    received_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMPTZ,

    CONSTRAINT chk_square_webhook_environment
        CHECK (environment IN ('sandbox', 'production')),

    CONSTRAINT chk_square_webhook_routing_status
        CHECK (
            routing_status IN (
                'unrouted',
                'routed',
                'ignored',
                'error'
            )
        ),

    CONSTRAINT chk_square_webhook_processing_status
        CHECK (
            processing_status IN (
                'received',
                'processing',
                'processed',
                'ignored',
                'error'
            )
        ),

    CONSTRAINT fk_square_webhook_connection
        FOREIGN KEY (square_connection_id)
        REFERENCES square_connections (
            square_connection_id
        )
        ON DELETE SET NULL,

    CONSTRAINT fk_square_webhook_workspace
        FOREIGN KEY (business_unit_id, spa_id)
        REFERENCES business_units (
            business_unit_id,
            spa_id
        ),

    CONSTRAINT uq_square_webhook_event
        UNIQUE (
            environment,
            square_event_id
        )
);


CREATE INDEX IF NOT EXISTS
    idx_square_webhook_unrouted
ON square_webhook_events (
    environment,
    received_at
)
WHERE routing_status = 'unrouted';


CREATE INDEX IF NOT EXISTS
    idx_square_webhook_payment
ON square_webhook_events (
    environment,
    square_payment_id
)
WHERE square_payment_id IS NOT NULL;


-- =========================================================
-- SQUARE PAYMENTS / RECONCILIATION STAGING
--
-- Square monetary values are stored exactly in the provider's
-- smallest currency unit (for USD, cents). Conversion to PSP
-- NUMERIC dollar fields happens only when Income is written.
-- =========================================================

CREATE TABLE IF NOT EXISTS square_payments (
    square_payment_record_id BIGSERIAL PRIMARY KEY,

    square_connection_id BIGINT NOT NULL,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    environment VARCHAR(20) NOT NULL,

    square_payment_id VARCHAR(255) NOT NULL,
    square_order_id VARCHAR(255),
    square_customer_id VARCHAR(255),
    square_location_id VARCHAR(255),
    merchant_id VARCHAR(255),

    payment_status VARCHAR(50),
    tender_type VARCHAR(80),
    currency VARCHAR(10),

    amount_cents BIGINT,
    service_amount_cents BIGINT,
    retail_amount_cents BIGINT,
    tax_amount_cents BIGINT,
    tip_amount_cents BIGINT,
    discount_amount_cents BIGINT,
    processing_fee_cents BIGINT,
    refunded_amount_cents BIGINT,
    net_received_cents BIGINT,

    square_created_at TIMESTAMPTZ,
    square_updated_at TIMESTAMPTZ,

    appointment_id INTEGER,
    client_id INTEGER,
    income_id INTEGER,

    reconciliation_status VARCHAR(30)
        NOT NULL DEFAULT 'pending',

    match_method VARCHAR(80),
    match_notes TEXT,

    retrieved_at TIMESTAMPTZ,
    last_synced_at TIMESTAMPTZ,
    reconciled_at TIMESTAMPTZ,

    reviewed_by INTEGER,

    raw_payment JSONB,
    raw_order JSONB,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_square_payments_environment
        CHECK (environment IN ('sandbox', 'production')),

    CONSTRAINT chk_square_payments_reconciliation_status
        CHECK (
            reconciliation_status IN (
                'pending',
                'matched',
                'review',
                'reconciled',
                'ignored',
                'error'
            )
        ),

    CONSTRAINT fk_square_payments_connection_workspace
        FOREIGN KEY (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        )
        REFERENCES square_connections (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_payments_workspace
        FOREIGN KEY (business_unit_id, spa_id)
        REFERENCES business_units (
            business_unit_id,
            spa_id
        ),

    CONSTRAINT fk_square_payments_appointment
        FOREIGN KEY (
            appointment_id,
            spa_id,
            business_unit_id
        )
        REFERENCES appointments (
            appointment_id,
            spa_id,
            business_unit_id
        )
        ON DELETE SET NULL (appointment_id),

    CONSTRAINT fk_square_payments_client
        FOREIGN KEY (
            client_id,
            spa_id,
            business_unit_id
        )
        REFERENCES clients (
            client_id,
            spa_id,
            business_unit_id
        )
        ON DELETE SET NULL (client_id),

    CONSTRAINT fk_square_payments_income
        FOREIGN KEY (
            income_id,
            spa_id,
            business_unit_id
        )
        REFERENCES income (
            income_id,
            spa_id,
            business_unit_id
        )
        ON DELETE SET NULL (income_id),

    CONSTRAINT fk_square_payments_reviewed_by
        FOREIGN KEY (reviewed_by)
        REFERENCES users (
            user_id
        )
        ON DELETE SET NULL,

    CONSTRAINT uq_square_payment
        UNIQUE (
            environment,
            square_payment_id
        ),

    CONSTRAINT uq_square_payment_workspace_identity
        UNIQUE (
            square_payment_record_id,
            spa_id,
            business_unit_id
        )
);


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_square_payment_income
ON square_payments (
    income_id
)
WHERE income_id IS NOT NULL;


CREATE INDEX IF NOT EXISTS
    idx_square_payments_workspace_status
ON square_payments (
    spa_id,
    business_unit_id,
    reconciliation_status,
    square_created_at DESC
);


CREATE INDEX IF NOT EXISTS
    idx_square_payments_recent_location
ON square_payments (
    environment,
    square_location_id,
    square_created_at DESC
);


CREATE INDEX IF NOT EXISTS
    idx_square_payments_order
ON square_payments (
    environment,
    square_order_id
)
WHERE square_order_id IS NOT NULL;


CREATE INDEX IF NOT EXISTS
    idx_square_payments_customer
ON square_payments (
    environment,
    square_customer_id
)
WHERE square_customer_id IS NOT NULL;


-- =========================================================
-- SQUARE CUSTOMER -> PSP CLIENT MAPPING
--
-- Persistent mappings take priority over future email/phone
-- fallback matching. A Square customer is never guessed into a
-- different PSP workspace.
-- =========================================================

CREATE TABLE IF NOT EXISTS square_customer_mappings (
    square_customer_mapping_id BIGSERIAL PRIMARY KEY,

    square_connection_id BIGINT NOT NULL,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    environment VARCHAR(20) NOT NULL,

    square_customer_id VARCHAR(255) NOT NULL,
    client_id INTEGER NOT NULL,

    match_method VARCHAR(80),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    verified_by INTEGER,
    verified_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_square_customer_environment
        CHECK (environment IN ('sandbox', 'production')),

    CONSTRAINT fk_square_customer_connection_workspace
        FOREIGN KEY (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        )
        REFERENCES square_connections (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_customer_workspace
        FOREIGN KEY (business_unit_id, spa_id)
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_customer_client
        FOREIGN KEY (
            client_id,
            spa_id,
            business_unit_id
        )
        REFERENCES clients (
            client_id,
            spa_id,
            business_unit_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_customer_verified_by
        FOREIGN KEY (verified_by)
        REFERENCES users (
            user_id
        )
        ON DELETE SET NULL,

    CONSTRAINT uq_square_customer_mapping
        UNIQUE (
            square_connection_id,
            square_customer_id
        )
);


CREATE INDEX IF NOT EXISTS
    idx_square_customer_mapping_client
ON square_customer_mappings (
    spa_id,
    business_unit_id,
    client_id
)
WHERE is_active = TRUE;


-- =========================================================
-- SQUARE CATALOG -> PSP MAPPING
--
-- A Square catalog variation can map to either:
--   1. a PSP inventory product
--   2. a PSP service type
--
-- Never both.
-- =========================================================

CREATE TABLE IF NOT EXISTS square_catalog_mappings (
    square_catalog_mapping_id BIGSERIAL PRIMARY KEY,

    square_connection_id BIGINT NOT NULL,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    environment VARCHAR(20) NOT NULL,

    square_catalog_object_id VARCHAR(255) NOT NULL,
    square_item_id VARCHAR(255),

    square_name VARCHAR(255),
    square_sku VARCHAR(255),

    mapping_type VARCHAR(30) NOT NULL,

    inventory_product_id INTEGER,
    service_type_id INTEGER,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    verified_by INTEGER,
    verified_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_square_catalog_environment
        CHECK (environment IN ('sandbox', 'production')),

    CONSTRAINT chk_square_catalog_mapping_type
        CHECK (
            mapping_type IN (
                'inventory_product',
                'service_type'
            )
        ),

    CONSTRAINT chk_square_catalog_single_target
        CHECK (
            (
                mapping_type = 'inventory_product'
                AND inventory_product_id IS NOT NULL
                AND service_type_id IS NULL
            )
            OR
            (
                mapping_type = 'service_type'
                AND service_type_id IS NOT NULL
                AND inventory_product_id IS NULL
            )
        ),

    CONSTRAINT fk_square_catalog_connection_workspace
        FOREIGN KEY (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        )
        REFERENCES square_connections (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_catalog_workspace
        FOREIGN KEY (business_unit_id, spa_id)
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_catalog_inventory_product
        FOREIGN KEY (
            inventory_product_id,
            spa_id,
            business_unit_id
        )
        REFERENCES inventory_products (
            product_id,
            spa_id,
            business_unit_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_catalog_service_type
        FOREIGN KEY (
            service_type_id,
            spa_id
        )
        REFERENCES service_name_types (
            service_type_id,
            spa_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_catalog_verified_by
        FOREIGN KEY (verified_by)
        REFERENCES users (
            user_id
        )
        ON DELETE SET NULL,

    CONSTRAINT uq_square_catalog_mapping
        UNIQUE (
            square_connection_id,
            square_catalog_object_id
        ),

    CONSTRAINT uq_square_catalog_mapping_workspace_identity
        UNIQUE (
            square_catalog_mapping_id,
            spa_id,
            business_unit_id
        )
);


CREATE INDEX IF NOT EXISTS
    idx_square_catalog_inventory_product
ON square_catalog_mappings (
    spa_id,
    business_unit_id,
    inventory_product_id
)
WHERE inventory_product_id IS NOT NULL
  AND is_active = TRUE;


CREATE INDEX IF NOT EXISTS
    idx_square_catalog_service_type
ON square_catalog_mappings (
    spa_id,
    business_unit_id,
    service_type_id
)
WHERE service_type_id IS NOT NULL
  AND is_active = TRUE;


-- =========================================================
-- SQUARE PAYMENT LINE ITEMS
--
-- Retain Square order-line detail so PSP can split service vs
-- retail and create one inventory movement per mapped retail
-- line after the Income record is saved.
-- =========================================================

CREATE TABLE IF NOT EXISTS square_payment_line_items (
    square_payment_line_item_id BIGSERIAL PRIMARY KEY,

    square_payment_record_id BIGINT NOT NULL,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    line_sequence INTEGER NOT NULL,

    square_order_line_item_uid VARCHAR(255),
    square_catalog_object_id VARCHAR(255),
    square_item_id VARCHAR(255),

    item_name VARCHAR(255),
    sku VARCHAR(255),

    quantity_text VARCHAR(80),
    quantity_numeric NUMERIC(18, 6),

    base_price_cents BIGINT,
    gross_amount_cents BIGINT,
    discount_amount_cents BIGINT,
    tax_amount_cents BIGINT,
    total_amount_cents BIGINT,

    item_classification VARCHAR(30)
        NOT NULL DEFAULT 'unknown',

    square_catalog_mapping_id BIGINT,

    inventory_movement_id INTEGER,

    reconciliation_status VARCHAR(30)
        NOT NULL DEFAULT 'pending',

    raw_line_item JSONB,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_square_line_item_sequence
        CHECK (line_sequence > 0),

    CONSTRAINT chk_square_line_item_classification
        CHECK (
            item_classification IN (
                'unknown',
                'service',
                'retail',
                'other'
            )
        ),

    CONSTRAINT chk_square_line_item_status
        CHECK (
            reconciliation_status IN (
                'pending',
                'mapped',
                'review',
                'posted',
                'ignored',
                'error'
            )
        ),

    CONSTRAINT fk_square_line_payment_workspace
        FOREIGN KEY (
            square_payment_record_id,
            spa_id,
            business_unit_id
        )
        REFERENCES square_payments (
            square_payment_record_id,
            spa_id,
            business_unit_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_square_line_catalog_mapping
        FOREIGN KEY (
            square_catalog_mapping_id,
            spa_id,
            business_unit_id
        )
        REFERENCES square_catalog_mappings (
            square_catalog_mapping_id,
            spa_id,
            business_unit_id
        )
        ON DELETE SET NULL (square_catalog_mapping_id),

    CONSTRAINT fk_square_line_inventory_movement
        FOREIGN KEY (
            inventory_movement_id,
            spa_id,
            business_unit_id
        )
        REFERENCES inventory_movements (
            movement_id,
            spa_id,
            business_unit_id
        )
        ON DELETE SET NULL (inventory_movement_id),

    CONSTRAINT uq_square_payment_line_sequence
        UNIQUE (
            square_payment_record_id,
            line_sequence
        )
);


CREATE INDEX IF NOT EXISTS
    idx_square_payment_lines_workspace
ON square_payment_line_items (
    spa_id,
    business_unit_id,
    reconciliation_status
);


CREATE INDEX IF NOT EXISTS
    idx_square_payment_lines_catalog_object
ON square_payment_line_items (
    square_catalog_object_id
)
WHERE square_catalog_object_id IS NOT NULL;


COMMIT;
