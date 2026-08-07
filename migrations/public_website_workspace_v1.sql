BEGIN;

-- =========================================================
-- PUBLIC WEBSITE WORKSPACE FOUNDATION — EXPAND PHASE
--
-- This migration is intentionally non-destructive.
-- It adds workspace ownership and reusable website structures
-- without removing the existing spa-level columns/constraints.
-- =========================================================


-- ---------------------------------------------------------
-- 1. PUBLIC WEBSITE SETTINGS
-- ---------------------------------------------------------

ALTER TABLE public_website_settings
    ADD COLUMN IF NOT EXISTS business_unit_id INTEGER,
    ADD COLUMN IF NOT EXISTS website_tagline VARCHAR(180),
    ADD COLUMN IF NOT EXISTS hero_description TEXT;


-- Preserve the currently deployed Clear Skin presentation.
UPDATE public_website_settings pws
SET
    website_tagline = COALESCE(
        pws.website_tagline,
        'Personalized Skincare'
    ),
    hero_description = COALESCE(
        pws.hero_description,
        'Enjoy professional skincare treatments created around your individual needs, goals, and comfort. Your appointment is more than a service—it is time dedicated to helping you feel confident in your skin.'
    )
WHERE EXISTS (
    SELECT 1
    FROM business_units bu
    WHERE bu.spa_id = pws.spa_id
      AND LOWER(BTRIM(bu.unit_name)) = 'clear skin esthetics'
);


-- Deterministic workspace backfill only when the spa has
-- exactly one active business unit.
UPDATE public_website_settings pws
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = pws.spa_id
      AND bu.is_active = TRUE
)
WHERE pws.business_unit_id IS NULL
  AND (
        SELECT COUNT(*)
        FROM business_units bu
        WHERE bu.spa_id = pws.spa_id
          AND bu.is_active = TRUE
      ) = 1;


-- Replace tenant-specific schema defaults with neutral defaults.
ALTER TABLE public_website_settings
    ALTER COLUMN about_heading
        SET DEFAULT 'About Our Business',
    ALTER COLUMN about_description
        SET DEFAULT '',
    ALTER COLUMN additional_menu_heading
        SET DEFAULT 'Additional Menu';


-- Workspace FK is added now while business_unit_id remains
-- nullable during the expand phase.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_public_website_settings_workspace'
    ) THEN
        ALTER TABLE public_website_settings
            ADD CONSTRAINT fk_public_website_settings_workspace
            FOREIGN KEY (business_unit_id, spa_id)
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
        WHERE conname = 'uq_public_website_settings_workspace'
    ) THEN
        ALTER TABLE public_website_settings
            ADD CONSTRAINT uq_public_website_settings_workspace
            UNIQUE (
                spa_id,
                business_unit_id
            );
    END IF;
END
$$;


CREATE INDEX IF NOT EXISTS
    idx_public_website_settings_workspace
ON public_website_settings (
    spa_id,
    business_unit_id
);


-- ---------------------------------------------------------
-- 2. PUBLIC WEBSITE ADDITIONAL MENU ITEMS
-- ---------------------------------------------------------

ALTER TABLE public_website_menu_items
    ADD COLUMN IF NOT EXISTS business_unit_id INTEGER;


UPDATE public_website_menu_items pwm
SET business_unit_id = (
    SELECT MIN(bu.business_unit_id)
    FROM business_units bu
    WHERE bu.spa_id = pwm.spa_id
      AND bu.is_active = TRUE
)
WHERE pwm.business_unit_id IS NULL
  AND (
        SELECT COUNT(*)
        FROM business_units bu
        WHERE bu.spa_id = pwm.spa_id
          AND bu.is_active = TRUE
      ) = 1;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_public_website_menu_items_workspace'
    ) THEN
        ALTER TABLE public_website_menu_items
            ADD CONSTRAINT fk_public_website_menu_items_workspace
            FOREIGN KEY (business_unit_id, spa_id)
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
        WHERE conname = 'uq_public_website_menu_item_workspace_name'
    ) THEN
        ALTER TABLE public_website_menu_items
            ADD CONSTRAINT uq_public_website_menu_item_workspace_name
            UNIQUE (
                spa_id,
                business_unit_id,
                item_name
            );
    END IF;
END
$$;


CREATE INDEX IF NOT EXISTS
    idx_public_website_menu_items_workspace_active
ON public_website_menu_items (
    spa_id,
    business_unit_id,
    is_active,
    sort_order
);


-- ---------------------------------------------------------
-- 3. WORKSPACE-LEVEL WEBSITE SERVICE PRESENTATION
--
-- service_name_types remains the shared master service catalog.
-- provider_service_types remains provider/booking configuration.
-- This table controls website-specific service presentation.
-- ---------------------------------------------------------

CREATE UNIQUE INDEX IF NOT EXISTS
    idx_service_name_types_service_spa_unique
ON service_name_types (
    service_type_id,
    spa_id
);


CREATE TABLE IF NOT EXISTS public_website_services (
    public_website_service_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,
    service_type_id INTEGER NOT NULL,

    public_description TEXT,
    show_on_public_website BOOLEAN NOT NULL DEFAULT FALSE,
    website_sort_order INTEGER,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_public_website_service_workspace
        UNIQUE (
            spa_id,
            business_unit_id,
            service_type_id
        ),

    CONSTRAINT chk_public_website_service_sort_order
        CHECK (
            website_sort_order IS NULL
            OR website_sort_order BETWEEN 1 AND 999
        ),

    CONSTRAINT fk_public_website_service_workspace
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE,

    CONSTRAINT fk_public_website_service_catalog
        FOREIGN KEY (
            service_type_id,
            spa_id
        )
        REFERENCES service_name_types (
            service_type_id,
            spa_id
        )
        ON DELETE CASCADE
);


CREATE INDEX IF NOT EXISTS
    idx_public_website_services_visible
ON public_website_services (
    spa_id,
    business_unit_id,
    show_on_public_website,
    website_sort_order
);


-- Preserve the current service website presentation whenever
-- a spa has exactly one active business unit.
INSERT INTO public_website_services (
    spa_id,
    business_unit_id,
    service_type_id,
    public_description,
    show_on_public_website,
    website_sort_order
)
SELECT
    snt.spa_id,
    bu.business_unit_id,
    snt.service_type_id,
    snt.public_description,
    snt.show_on_public_website,
    snt.website_sort_order
FROM service_name_types snt
JOIN business_units bu
  ON bu.spa_id = snt.spa_id
 AND bu.is_active = TRUE
WHERE (
    SELECT COUNT(*)
    FROM business_units bu_count
    WHERE bu_count.spa_id = snt.spa_id
      AND bu_count.is_active = TRUE
) = 1
ON CONFLICT (
    spa_id,
    business_unit_id,
    service_type_id
)
DO NOTHING;


-- ---------------------------------------------------------
-- 4. PUBLIC WEBSITE DOMAIN / HOSTNAME ROUTING
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS public_website_domains (
    public_website_domain_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    hostname VARCHAR(255) NOT NULL,
    domain_type VARCHAR(30) NOT NULL
        DEFAULT 'hosted_subdomain',

    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_public_website_domain_hostname
        UNIQUE (hostname),

    CONSTRAINT chk_public_website_domain_hostname
        CHECK (
            hostname = LOWER(BTRIM(hostname))
            AND hostname <> ''
            AND hostname NOT LIKE '%/%'
            AND hostname NOT LIKE '%:%'
        ),

    CONSTRAINT chk_public_website_domain_type
        CHECK (
            domain_type IN (
                'hosted_subdomain',
                'custom_domain'
            )
        ),

    CONSTRAINT fk_public_website_domain_workspace
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE
);


CREATE INDEX IF NOT EXISTS
    idx_public_website_domains_workspace
ON public_website_domains (
    spa_id,
    business_unit_id,
    is_active
);


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_public_website_domains_primary_workspace
ON public_website_domains (
    spa_id,
    business_unit_id
)
WHERE is_primary = TRUE
  AND is_active = TRUE;


-- Preserve the currently deployed Clear Skin hostname.
INSERT INTO public_website_domains (
    spa_id,
    business_unit_id,
    hostname,
    domain_type,
    is_primary,
    is_active
)
SELECT
    pws.spa_id,
    pws.business_unit_id,
    'clearskinesthetics.peachsuitepro.com',
    'hosted_subdomain',
    TRUE,
    TRUE
FROM public_website_settings pws
JOIN business_units bu
  ON bu.business_unit_id = pws.business_unit_id
 AND bu.spa_id = pws.spa_id
WHERE pws.business_unit_id IS NOT NULL
  AND LOWER(BTRIM(bu.unit_name)) = 'clear skin esthetics'
ON CONFLICT (hostname)
DO NOTHING;


-- ---------------------------------------------------------
-- 5. GENERIC WEBSITE LINKS
--
-- May be used for provider websites, parent spa websites,
-- social profiles, gift cards, stores, or other URLs.
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS public_website_links (
    public_website_link_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL,
    business_unit_id INTEGER NOT NULL,

    link_label VARCHAR(180) NOT NULL,
    link_url TEXT NOT NULL,

    sort_order INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_public_website_link_sort_order
        CHECK (
            sort_order IS NULL
            OR sort_order BETWEEN 1 AND 999
        ),

    CONSTRAINT chk_public_website_link_url
        CHECK (
            link_url ~* '^https?://'
        ),

    CONSTRAINT fk_public_website_link_workspace
        FOREIGN KEY (
            business_unit_id,
            spa_id
        )
        REFERENCES business_units (
            business_unit_id,
            spa_id
        )
        ON DELETE CASCADE
);


CREATE INDEX IF NOT EXISTS
    idx_public_website_links_workspace_active
ON public_website_links (
    spa_id,
    business_unit_id,
    is_active,
    sort_order
);


COMMIT;
