-- Workspace-specific display-label overrides for Client Information.
--
-- Backend client/health-profile field names never change.
-- PSP default labels are defined in application code.
-- This table stores only workspace-specific display overrides.

CREATE TABLE client_information_labels (
    client_information_label_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    field_key VARCHAR(100) NOT NULL,
    custom_label VARCHAR(100) NOT NULL,

    updated_by INTEGER NULL
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT client_information_labels_workspace_fk
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        ),

    CONSTRAINT client_information_labels_field_key_not_blank
        CHECK (
            LENGTH(TRIM(field_key)) > 0
        ),

    CONSTRAINT client_information_labels_custom_label_not_blank
        CHECK (
            LENGTH(TRIM(custom_label)) > 0
        ),

    CONSTRAINT client_information_labels_workspace_field_unique
        UNIQUE (
            spa_id,
            business_unit_id,
            field_key
        )
);

CREATE INDEX client_information_labels_workspace_idx
    ON client_information_labels (
        spa_id,
        business_unit_id
    );
