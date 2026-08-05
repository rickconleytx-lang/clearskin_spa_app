BEGIN;

ALTER TABLE public_website_settings
    ADD COLUMN IF NOT EXISTS
        show_additional_menu_section
        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS
        additional_menu_heading
        VARCHAR(180) NOT NULL
        DEFAULT 'Additional Add-ons & Menu',
    ADD COLUMN IF NOT EXISTS
        additional_menu_description
        TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS
    public_website_menu_items (
        menu_item_id SERIAL PRIMARY KEY,
        spa_id INTEGER NOT NULL
            REFERENCES spas(spa_id)
            ON DELETE CASCADE,
        item_name VARCHAR(180) NOT NULL,
        price NUMERIC(10, 2) NOT NULL
            CHECK (price >= 0),
        sort_order INTEGER,
        is_active BOOLEAN NOT NULL
            DEFAULT TRUE,
        created_at TIMESTAMP NOT NULL
            DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL
            DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT
            public_website_menu_items_spa_name_key
            UNIQUE (spa_id, item_name)
    );

CREATE INDEX IF NOT EXISTS
    idx_public_website_menu_items_spa_active
ON public_website_menu_items (
    spa_id,
    is_active,
    sort_order
);

COMMIT;
